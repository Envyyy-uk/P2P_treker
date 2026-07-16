"""Торгові обмеження біржі: tick/step size, мінімальні обсяг/notional
(Фаза 4, п.4). Точність ціни/кількості випливає з tick/step size —
окремих полів "precision" немає, щоб не дублювати те саме обмеження.

Реальні значення надаються `exchangeInfo`-подібним endpoint'ом кожної
біржі і мають періодично оновлюватись (той самий механізм, що й
`fee_refresh_interval_hours` для комісій, Фаза 0, п.5) — тут дефолти
статичні в конфігурації; REST-клієнт для періодичного refresh — майбутня
робота разом з підключенням реальних торгових endpoint'ів бірж.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SymbolRules:
    tick_size: Decimal
    step_size: Decimal
    min_quantity: Decimal
    min_notional: Decimal


@dataclass(frozen=True)
class OrderValidationResult:
    valid: bool
    violations: list[str]


def round_to_tick(price: Decimal, tick_size: Decimal) -> Decimal:
    """Округлює ВНИЗ до найближчого кратного tick_size (ніколи не покращує ціну)."""
    if tick_size <= 0:
        raise ValueError("tick_size must be positive")
    return (price // tick_size) * tick_size


def round_to_step(quantity: Decimal, step_size: Decimal) -> Decimal:
    """Округлює ВНИЗ до найближчого кратного step_size (ніколи не збільшує обсяг)."""
    if step_size <= 0:
        raise ValueError("step_size must be positive")
    return (quantity // step_size) * step_size


def validate_order(quantity: Decimal, price: Decimal, rules: SymbolRules) -> OrderValidationResult:
    """Перевіряє ордер проти обмежень біржі. Не кидає виняток — повертає
    список порушень, щоб виклик міг вирішити (відхилити/скоригувати)."""
    violations: list[str] = []
    if quantity <= 0:
        violations.append("quantity must be positive")
    if price <= 0:
        violations.append("price must be positive")
    if violations:
        return OrderValidationResult(valid=False, violations=violations)

    if quantity < rules.min_quantity:
        violations.append(f"quantity {quantity} below min_quantity {rules.min_quantity}")
    notional = quantity * price
    if notional < rules.min_notional:
        violations.append(f"notional {notional} below min_notional {rules.min_notional}")
    if quantity != round_to_step(quantity, rules.step_size):
        violations.append(f"quantity {quantity} not aligned to step_size {rules.step_size}")
    if price != round_to_tick(price, rules.tick_size):
        violations.append(f"price {price} not aligned to tick_size {rules.tick_size}")
    return OrderValidationResult(valid=not violations, violations=violations)
