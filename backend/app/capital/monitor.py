"""Модель капіталу (Фаза 4.1): моніторинг балансу по біржах (base/quote,
available/locked), target allocation і сигнал про необхідність
ребалансування. Ребалансування навмисно лише РУЧНЕ (план, п.9): цей
модуль тільки рахує і сигналізує, ніколи сам не переказує кошти між
біржами. `record_manual_transfer` лише фіксує в локальному обліку
переказ, який оператор уже виконав на реальних біржах.

Перевірка "чи вистачає капіталу для напрямку" (план, п.6: "якщо балансу
недостатньо, відповідний напрямок тимчасово вимикається") реалізована як
проста real-time перевірка поверх `BalanceManager`, а не окремий stateful
prapor "увімкнено/вимкнено" — `BalanceManager` і так є єдиним джерелом
правди про доступні кошти, дублювати цей стан немає сенсу.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.core.config import CapitalConfig
from app.models.enums import Exchange
from app.paper_trading.balance import BalanceManager

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class AssetCapitalStatus:
    asset: str
    total: Decimal
    available: Decimal
    locked: Decimal


@dataclass(frozen=True)
class ExchangeCapitalStatus:
    exchange: Exchange
    quote_asset_status: AssetCapitalStatus
    base_asset_statuses: dict[str, AssetCapitalStatus]
    target_pct: Decimal | None
    actual_pct: Decimal | None
    deviation_pct: Decimal | None


@dataclass(frozen=True)
class RebalanceSignal:
    asset: str
    from_exchange: Exchange
    to_exchange: Exchange
    amount: Decimal
    reason: str


@dataclass(frozen=True)
class DirectionAvailability:
    symbol: str
    buy_exchange: Exchange
    sell_exchange: Exchange
    available: bool
    reason: str | None


def _asset_status(balances: BalanceManager, exchange: Exchange, asset: str) -> AssetCapitalStatus:
    balance = balances.get(exchange, asset)
    return AssetCapitalStatus(
        asset=asset, total=balance.total, available=balance.available, locked=balance.locked
    )


class CapitalMonitor:
    def __init__(self, balances: BalanceManager, config: CapitalConfig) -> None:
        self._balances = balances
        self._config = config

    def snapshot(
        self, exchanges: list[Exchange], base_assets: list[str]
    ) -> list[ExchangeCapitalStatus]:
        """Розподіл капіталу рахується тільки за `quote_asset` (план не
        вимагає конвертації різних активів у спільну одиницю виміру —
        конвертація base-активів у USD-еквівалент вимагала б live цін і
        є окремою, ширшою задачею за межами Фази 4.1)."""
        quote_totals = {
            exchange: self._balances.get(exchange, self._config.quote_asset).total
            for exchange in exchanges
        }
        total_capital = sum(quote_totals.values(), _ZERO)

        statuses = []
        for exchange in exchanges:
            quote_status = _asset_status(self._balances, exchange, self._config.quote_asset)
            base_statuses = {
                asset: _asset_status(self._balances, exchange, asset) for asset in base_assets
            }
            target_pct = self._config.target_allocation.get(exchange)
            actual_pct = (
                (quote_totals[exchange] / total_capital) * _HUNDRED if total_capital > 0 else None
            )
            deviation_pct = (
                actual_pct - target_pct
                if target_pct is not None and actual_pct is not None
                else None
            )
            statuses.append(
                ExchangeCapitalStatus(
                    exchange=exchange,
                    quote_asset_status=quote_status,
                    base_asset_statuses=base_statuses,
                    target_pct=target_pct,
                    actual_pct=actual_pct,
                    deviation_pct=deviation_pct,
                )
            )
        return statuses

    def rebalance_signals(self, exchanges: list[Exchange]) -> list[RebalanceSignal]:
        """Список сигналів "перекинь X quote_asset з біржі A на біржу B",
        поки фактичний розподіл не наблизиться до target у межах порогу.
        Жадібне спарювання найбільшого надлишку з найбільшим дефіцитом —
        не претендує на єдино оптимальний план переказів, лише на
        мінімально достатній."""
        statuses = self.snapshot(exchanges, base_assets=[])
        total_capital = sum((s.quote_asset_status.total for s in statuses), _ZERO)
        if total_capital <= 0:
            return []

        threshold = self._config.rebalance_threshold_pct
        over = [
            (s, (s.deviation_pct / _HUNDRED) * total_capital)
            for s in statuses
            if s.deviation_pct is not None and s.deviation_pct > threshold
        ]
        under = [
            (s, (-s.deviation_pct / _HUNDRED) * total_capital)
            for s in statuses
            if s.deviation_pct is not None and s.deviation_pct < -threshold
        ]
        over.sort(key=lambda pair: pair[1], reverse=True)
        under.sort(key=lambda pair: pair[1], reverse=True)

        signals: list[RebalanceSignal] = []
        i, j = 0, 0
        while i < len(over) and j < len(under):
            over_status, excess = over[i]
            under_status, deficit = under[j]
            amount = min(excess, deficit)
            if amount > 0:
                # Гарантовано not None фільтром вище (under лише з deviation_pct < -threshold).
                under_deviation = under_status.deviation_pct
                assert under_deviation is not None
                signals.append(
                    RebalanceSignal(
                        asset=self._config.quote_asset,
                        from_exchange=over_status.exchange,
                        to_exchange=under_status.exchange,
                        amount=amount,
                        reason=(
                            f"{over_status.exchange.value} вище target на "
                            f"{over_status.deviation_pct}%, "
                            f"{under_status.exchange.value} нижче target на "
                            f"{-under_deviation}%"
                        ),
                    )
                )
            excess -= amount
            deficit -= amount
            over[i] = (over_status, excess)
            under[j] = (under_status, deficit)
            if excess <= 0:
                i += 1
            if deficit <= 0:
                j += 1
        return signals

    def check_direction(
        self,
        symbol: str,
        buy_exchange: Exchange,
        sell_exchange: Exchange,
        quantity: Decimal,
        buy_price: Decimal,
    ) -> DirectionAvailability:
        """Real-time перевірка, чи вистачає капіталу на обидві ноги
        арбітражу для (symbol, buy_exchange, sell_exchange) — план, п.6."""
        base_asset = symbol.split("-")[0]
        quote_needed = quantity * buy_price
        buy_available = self._balances.available(buy_exchange, self._config.quote_asset)
        if buy_available < quote_needed:
            return DirectionAvailability(
                symbol=symbol,
                buy_exchange=buy_exchange,
                sell_exchange=sell_exchange,
                available=False,
                reason=(
                    f"insufficient {self._config.quote_asset} on {buy_exchange.value}: "
                    f"available={buy_available} < required={quote_needed}"
                ),
            )
        sell_available = self._balances.available(sell_exchange, base_asset)
        if sell_available < quantity:
            return DirectionAvailability(
                symbol=symbol,
                buy_exchange=buy_exchange,
                sell_exchange=sell_exchange,
                available=False,
                reason=(
                    f"insufficient {base_asset} on {sell_exchange.value}: "
                    f"available={sell_available} < required={quantity}"
                ),
            )
        return DirectionAvailability(
            symbol=symbol,
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            available=True,
            reason=None,
        )


def record_manual_transfer(
    balances: BalanceManager,
    asset: str,
    from_exchange: Exchange,
    to_exchange: Exchange,
    amount: Decimal,
) -> bool:
    """Фіксує в локальному обліку переказ між біржами, який оператор уже
    виконав вручну (план, Фаза 4.1, п.9: ребалансування спочатку ручне) —
    НЕ ініціює жоден реальний переказ. False без жодної мутації балансу,
    якщо на `from_exchange` недостатньо `available`."""
    if not balances.debit(from_exchange, asset, amount):
        return False
    balances.credit(to_exchange, asset, amount)
    return True
