"""Базові виключення платформи (Фаза 0.3)."""


class PlatformError(Exception):
    """Базовий клас усіх помилок платформи."""


class ConfigurationError(PlatformError):
    """Невалідна конфігурація — застосунок не має стартувати."""


class ClockDriftError(PlatformError):
    """Дрейф системного часу перевищує допустимий поріг (Фаза 0, п.11)."""


class StaleQuoteError(PlatformError):
    """Котирування застаріле і не може використовуватись у розрахунках."""


class MarketTypeMismatchError(PlatformError):
    """Спроба порівняти котирування різних market types (заборонено планом)."""


class SymbolMappingError(PlatformError):
    """Немає відповідності символу для біржі."""
