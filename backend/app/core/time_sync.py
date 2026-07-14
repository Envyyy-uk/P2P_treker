"""Перевірка дрейфу системного часу при старті (Фаза 0, п.10–11).

Freshness-логіка (quote age, timestamp diff) вимагає коректного часу.
Кілька NTP-серверів — резерв один одному: беремо перший успішний offset.
"""

import asyncio
import logging
from dataclasses import dataclass

import ntplib  # type: ignore[import-untyped]

from app.core.exceptions import ClockDriftError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClockDriftResult:
    server: str | None
    offset_ms: float | None  # None — жоден сервер не відповів

    @property
    def known(self) -> bool:
        return self.offset_ms is not None


def _query_offset_ms(server: str, timeout_s: float) -> float:
    client = ntplib.NTPClient()
    response = client.request(server, version=3, timeout=timeout_s)
    return float(response.offset) * 1000.0


async def measure_clock_drift(servers: list[str], timeout_s: float) -> ClockDriftResult:
    """Опитує NTP-сервери по черзі; повертає перший успішний offset."""
    for server in servers:
        try:
            offset_ms = await asyncio.to_thread(_query_offset_ms, server, timeout_s)
            return ClockDriftResult(server=server, offset_ms=offset_ms)
        except Exception as exc:  # ntplib кидає різнотипні мережеві помилки
            logger.warning("NTP server %s unavailable: %s", server, exc)
    return ClockDriftResult(server=None, offset_ms=None)


async def check_clock_drift_on_startup(
    servers: list[str],
    max_drift_ms: int,
    fail_on_drift: bool,
    timeout_s: float,
) -> ClockDriftResult:
    """Стартова перевірка. Кидає ClockDriftError при перевищенні порогу.

    Якщо жоден сервер недоступний (мережа може блокувати UDP/123) —
    логуємо warning і не блокуємо старт: health endpoint покаже unknown.
    """
    result = await measure_clock_drift(servers, timeout_s)
    if not result.known:
        logger.warning("Clock drift unknown: no NTP server reachable (%s)", servers)
        return result

    assert result.offset_ms is not None
    logger.info("Clock drift vs %s: %.1f ms", result.server, result.offset_ms)
    if abs(result.offset_ms) > max_drift_ms:
        message = (
            f"System clock drift {result.offset_ms:.1f} ms exceeds limit "
            f"{max_drift_ms} ms (NTP: {result.server}). "
            "Fix NTP sync (see docs/phase-0/ntp-setup.md)."
        )
        if fail_on_drift:
            raise ClockDriftError(message)
        logger.error(message)
    return result
