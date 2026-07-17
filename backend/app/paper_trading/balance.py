"""Мінімальна модель балансу для Paper Trading (Фаза 4, п.4: доступний
баланс, зарезервовані кошти). Повна модель капіталу (цільовий розподіл
між біржами, сигнал ребалансування) — окрема Фаза 4.1; тут лише
перевірка "чи вистачає коштів" і резервування на час відкритого ордера.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from app.models.enums import Exchange

_ZERO = Decimal("0")


@dataclass
class AssetBalance:
    total: Decimal
    locked: Decimal = _ZERO

    @property
    def available(self) -> Decimal:
        return self.total - self.locked


@dataclass
class BalanceManager:
    _balances: dict[tuple[Exchange, str], AssetBalance] = field(default_factory=dict)

    def set_balance(self, exchange: Exchange, asset: str, total: Decimal) -> None:
        self._balances[(exchange, asset)] = AssetBalance(total=total)

    def get(self, exchange: Exchange, asset: str) -> AssetBalance:
        return self._balances.setdefault((exchange, asset), AssetBalance(total=_ZERO))

    def available(self, exchange: Exchange, asset: str) -> Decimal:
        return self.get(exchange, asset).available

    def reserve(self, exchange: Exchange, asset: str, amount: Decimal) -> bool:
        """Резервує кошти під відкритий ордер. False, якщо available < amount
        (баланс лишається незмінним у цьому разі)."""
        balance = self.get(exchange, asset)
        if balance.available < amount:
            return False
        balance.locked += amount
        return True

    def release(self, exchange: Exchange, asset: str, amount: Decimal) -> None:
        """Звільняє резерв без списання (скасування/відхилення ордера)."""
        balance = self.get(exchange, asset)
        balance.locked = max(_ZERO, balance.locked - amount)

    def settle(
        self, exchange: Exchange, asset: str, reserved_amount: Decimal, actual_amount: Decimal
    ) -> None:
        """Списує реально витрачену суму (може бути меншою за резерв через
        partial fill) і звільняє залишок резерву."""
        balance = self.get(exchange, asset)
        balance.locked = max(_ZERO, balance.locked - reserved_amount)
        balance.total -= actual_amount

    def credit(self, exchange: Exchange, asset: str, amount: Decimal) -> None:
        """Зараховує кошти (наприклад, виручку від продажу)."""
        balance = self.get(exchange, asset)
        balance.total += amount

    def debit(self, exchange: Exchange, asset: str, amount: Decimal) -> bool:
        """Списує кошти без попереднього резервування (напр. вихідна нога
        ручного переказу між біржами, Фаза 4.1). False, якщо available <
        amount — баланс лишається незмінним у цьому разі."""
        balance = self.get(exchange, asset)
        if balance.available < amount:
            return False
        balance.total -= amount
        return True

    def all_balances(self) -> dict[tuple[Exchange, str], AssetBalance]:
        """Знімок усіх балансів — для health/дебаг-ендпоінтів."""
        return dict(self._balances)
