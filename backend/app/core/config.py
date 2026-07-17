"""Конфігурація застосунку (Фаза 0.2) — Pydantic Settings.

Секції: Exchange / Trading / Database / WebSocket / Logging / Security /
Monitoring. Уся поведінка, що може змінюватись, винесена сюди — зміни
конфігурації не мають вимагати редагування бізнес-логіки.

Env-змінні використовують вкладений синтаксис з подвійним підкресленням:
    TRADING__MAX_QUOTE_AGE_MS=1000
    EXCHANGES__BINANCE__TAKER_FEE=0.001
"""

from decimal import Decimal
from enum import StrEnum
from functools import lru_cache

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.symbols import SYMBOL_MAP
from app.models.enums import Exchange, MarketType
from app.paper_trading.rules import SymbolRules


class Environment(StrEnum):
    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"


class QueueOverflowPolicy(StrEnum):
    """Політика переповнення async Queue запису в БД (Фаза 2, п.3)."""

    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"
    BLOCK = "block"  # не для live market data


class ExchangeConfig(BaseModel):
    """Налаштування однієї біржі, включно з комісіями (Фаза 0, п.5)."""

    enabled: bool = True
    # Дефолтні базові taker/maker fee (частки). Оновлюються періодично
    # через account/fee endpoint (fee_refresh_interval_hours), бо залежать
    # від VIP-рівня — не хардкодити назавжди.
    maker_fee: Decimal = Decimal("0.001")
    taker_fee: Decimal = Decimal("0.001")
    fee_refresh_interval_hours: int = Field(default=24, ge=1)
    # Read-only API-ключі (для fee endpoint). Ніколи не логуються.
    api_key: SecretStr | None = None
    api_secret: SecretStr | None = None
    api_passphrase: SecretStr | None = None  # потрібен тільки OKX
    api_key_created_at: str | None = None  # ISO-дата для політики ротації (90 днів)


class TradingConfig(BaseModel):
    """Пороги freshness, спреду та обсягу (Фаза 0, п.6–7; Фаза 0.2, п.5)."""

    market_type: MarketType = MarketType.SPOT
    symbols: list[str] = Field(default_factory=lambda: list(SYMBOL_MAP))
    max_quote_age_ms: int = Field(default=1000, ge=1)
    max_timestamp_diff_ms: int = Field(default=1500, ge=1)
    # Поріг net spread для фіксації spread event (частка, 0.001 = 0.1%).
    spread_threshold: Decimal = Decimal("0.001")
    min_executable_quantity: Decimal = Decimal("0")
    min_executable_notional: Decimal = Decimal("10")  # у quote-активі (USDT)

    @model_validator(mode="after")
    def _validate(self) -> "TradingConfig":
        if self.market_type is not MarketType.SPOT:
            raise ValueError("MVP supports only spot market (see PLAN.md, Phase 0)")
        unknown = set(self.symbols) - set(SYMBOL_MAP)
        if unknown:
            raise ValueError(f"Symbols without exchange mapping: {sorted(unknown)}")
        if not self.symbols:
            raise ValueError("At least one trading symbol is required")
        return self


class DatabaseConfig(BaseModel):
    # enabled=False — запуск без PostgreSQL (dev/тести): моніторинг працює,
    # історія не пишеться. Якщо enabled=True, але БД недоступна при старті,
    # застосунок продовжує моніторити і логує критичну помилку (збір даних
    # важливіший за їх персистентність у MVP).
    enabled: bool = True
    dsn: SecretStr = SecretStr("postgresql+asyncpg://arb:arb@localhost:5432/arbitrage")
    # Async queue запису (Фаза 2): bounded, з явною політикою переповнення.
    write_queue_size: int = Field(default=10_000, ge=100)
    queue_overflow_policy: QueueOverflowPolicy = QueueOverflowPolicy.DROP_OLDEST
    batch_max_rows: int = Field(default=500, ge=1)
    batch_max_interval_ms: int = Field(default=1000, ge=50)
    # Стратегія збереження (Фаза 2, п.5): один snapshot котирувань за секунду.
    quotes_sample_interval_ms: int = Field(default=1000, ge=100)
    # Таймаут флашу черги при graceful shutdown.
    shutdown_flush_timeout_s: float = Field(default=10.0, gt=0)


class RetentionConfig(BaseModel):
    """Retention, партиціонування і downsampling (Фаза 2.1).

    Сирі секундні дані partition-уються по днях (`quotes_1s`); downsample
    таблиці (`quotes_10s/1m/5m`) агрегуються окремим job'ом. `spread_events`
    зберігаються довше/постійно — це інша категорія даних (план, Фаза 2.1 п.3).
    """

    enabled: bool = True
    # Скільки денних партицій quotes_1s тримати (найновіші дні найважливіші).
    raw_retention_days: int = Field(default=7, ge=1)
    downsample_10s_retention_days: int = Field(default=30, ge=1)
    downsample_1m_retention_days: int = Field(default=180, ge=1)
    downsample_5m_retention_days: int = Field(default=365, ge=1)
    # None/0 -> зберігати spread_events постійно (вища критичність, план п.3, 2.2 п.5).
    spread_events_retention_days: int | None = None
    # Скільки майбутніх денних партицій quotes_1s тримати заздалегідь створеними.
    partition_ahead_days: int = Field(default=2, ge=1)
    maintenance_interval_hours: int = Field(default=24, ge=1)

    @field_validator("spread_events_retention_days", mode="before")
    @classmethod
    def _empty_string_means_unset(cls, v: object) -> object:
        # Порожній env var (RETENTION__SPREAD_EVENTS_RETENTION_DAYS=) має
        # означати "не задано" (постійне зберігання), а не помилку парсингу.
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class AnalyticsConfig(BaseModel):
    """API історії/статистики (Фаза 3)."""

    # Мінімальна тривалість spread event, щоб не враховувати випадкові
    # короткі стрибки (план, Фаза 3, п.2). Фільтр на рівні читання/API —
    # сам детектор (Фаза 2) пише всі перетини порогу без змін заднім числом.
    default_min_event_duration_ms: int = Field(default=500, ge=0)
    # Backend не повинен віддавати сотні тисяч точок (план, Фаза 3, п.5):
    # автовибір інтервалу downsampling + жорсткий cap на кількість точок.
    max_chart_points: int = Field(default=2000, ge=10)
    max_page_size: int = Field(default=500, ge=1, le=5000)
    default_page_size: int = Field(default=100, ge=1)


class BacktestConfig(BaseModel):
    """Historical Backtesting Engine (Фаза 3.1)."""

    # Захист від невибагливого запиту на роки історії в один прогін —
    # клієнту треба звузити період замість зависання процесу на годину.
    max_ticks_per_run: int = Field(default=500_000, ge=1_000)


class SymbolRulesConfig(BaseModel):
    """Дефолтні торгові обмеження (Фаза 4, п.4).

    Реальні значення надаються exchangeInfo-подібним endpoint'ом кожної
    біржі і мають періодично оновлюватись (той самий механізм, що й
    `fee_refresh_interval_hours` для комісій, Фаза 0, п.5) — тут лише
    статичні дефолти; REST-клієнт періодичного оновлення — майбутня робота.
    """

    tick_size: Decimal = Decimal("0.01")
    step_size: Decimal = Decimal("0.00001")
    min_quantity: Decimal = Decimal("0.00001")
    min_notional: Decimal = Decimal("10")

    def to_rules(self) -> SymbolRules:
        return SymbolRules(
            tick_size=self.tick_size,
            step_size=self.step_size,
            min_quantity=self.min_quantity,
            min_notional=self.min_notional,
        )


class PaperTradingConfig(BaseModel):
    """Paper Trading Engine (Фаза 4, п.5)."""

    default_rules: SymbolRulesConfig = Field(default_factory=SymbolRulesConfig)
    # Канонічний символ -> перевизначені правила (якщо відрізняються від дефолту).
    symbol_rules: dict[str, SymbolRulesConfig] = Field(default_factory=dict)
    # Затримка між двома ордерами арбітражної угоди (купівля/продаж не одночасні).
    inter_order_delay_ms: int = Field(default=200, ge=0)
    order_timeout_ms: int = Field(default=5_000, ge=1)
    # Проста симуляція rate limit біржі: макс. ордерів/скасувань за секунду.
    rate_limit_orders_per_second: int = Field(default=10, ge=1)

    def rules_for(self, symbol: str) -> SymbolRulesConfig:
        return self.symbol_rules.get(symbol, self.default_rules)


class CapitalConfig(BaseModel):
    """Модель капіталу (Фаза 4.1): капітал заздалегідь розподілений між
    біржами, купівля/продаж виконуються за рахунок уже наявних балансів
    (без withdraw під кожну угоду) — сама ця гарантія забезпечується
    `BalanceManager` (Фаза 4); тут лише target allocation і сигнал
    ребалансування поверх нього.

    `target_allocation` — частки капіталу (у %, 0–100) на біржу, мають
    сумувати рівно до 100, якщо задані. Порожній dict = ціль не
    налаштована: снепшот балансу все одно показує фактичний розподіл,
    сигнали ребалансування просто не генеруються.
    """

    quote_asset: str = "USDT"
    target_allocation: dict[Exchange, Decimal] = Field(default_factory=dict)
    # Відхилення фактичного розподілу від цільового (в % капіталу), що
    # вважається достатнім для сигналу "потрібне ребалансування".
    rebalance_threshold_pct: Decimal = Field(default=Decimal("10"), gt=0)

    @field_validator("target_allocation")
    @classmethod
    def _validate_allocation_sums_to_100(
        cls, v: dict[Exchange, Decimal]
    ) -> dict[Exchange, Decimal]:
        if v and abs(sum(v.values()) - Decimal("100")) > Decimal("0.01"):
            raise ValueError(f"target_allocation must sum to 100 (got {sum(v.values())})")
        return v


class WebSocketConfig(BaseModel):
    """Параметри і біржових WS, і push на frontend."""

    # Частота push на frontend: 5–10 оновлень/с за планом.
    frontend_push_rate_hz: int = Field(default=5, ge=1, le=10)
    client_queue_size: int = Field(default=100, ge=10)
    heartbeat_interval_s: int = Field(default=15, ge=1)
    # Біржові з'єднання
    reconnect_initial_delay_s: float = Field(default=1.0, gt=0)
    reconnect_max_delay_s: float = Field(default=60.0, gt=0)
    message_timeout_s: int = Field(default=10, ge=1)
    graceful_shutdown_timeout_s: int = Field(default=10, ge=1)


class LoggingConfig(BaseModel):
    level: str = "INFO"
    json_format: bool = True
    # Маскування секретів у логах (Фаза 0.1, п.5) — вимикати заборонено
    # в production; поле існує тільки для дебагу тестів.
    mask_secrets: bool = True


class SecurityConfig(BaseModel):
    api_key_max_age_days: int = Field(default=90, ge=1)
    api_key_rotation_warning_days: int = Field(default=14, ge=1)


class MonitoringConfig(BaseModel):
    """NTP / clock drift (Фаза 0, п.10–11) і health."""

    ntp_servers: list[str] = Field(
        default_factory=lambda: [
            "time.cloudflare.com",
            "time.google.com",
            "pool.ntp.org",
        ]
    )
    max_clock_drift_ms: int = Field(default=500, ge=1)
    fail_on_clock_drift: bool = True
    ntp_timeout_s: float = Field(default=3.0, gt=0)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="forbid",
    )

    environment: Environment = Environment.DEV
    app_name: str = "Spread Monitor MVP"
    app_version: str = "0.1.0"
    # Вимикає біржові WS-адаптери (тести/CI без мережі); движок і WS
    # push при цьому працюють на порожньому кеші.
    live_adapters_enabled: bool = True

    exchanges: dict[Exchange, ExchangeConfig] = Field(
        default_factory=lambda: {
            Exchange.BINANCE: ExchangeConfig(),
            Exchange.BYBIT: ExchangeConfig(),
            Exchange.OKX: ExchangeConfig(),
        }
    )
    trading: TradingConfig = Field(default_factory=TradingConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    analytics: AnalyticsConfig = Field(default_factory=AnalyticsConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    paper_trading: PaperTradingConfig = Field(default_factory=PaperTradingConfig)
    capital: CapitalConfig = Field(default_factory=CapitalConfig)
    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)

    @model_validator(mode="before")
    @classmethod
    def _merge_default_exchanges(cls, data: dict[str, object]) -> dict[str, object]:
        # Частковий env-override (напр. тільки EXCHANGES__BINANCE__TAKER_FEE)
        # не має прибирати решту бірж — доповнюємо відсутні дефолтами.
        exchanges = data.get("exchanges")
        if isinstance(exchanges, dict):
            for exchange in Exchange:
                exchanges.setdefault(exchange, ExchangeConfig())
        return data

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        enabled = [e for e, cfg in self.exchanges.items() if cfg.enabled]
        if len(enabled) < 2:
            raise ValueError("At least two enabled exchanges are required to compute spreads")
        if self.environment is Environment.PRODUCTION and not self.logging.mask_secrets:
            raise ValueError("Secret masking cannot be disabled in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Валідована конфігурація; помилка тут має валити старт застосунку."""
    return Settings()
