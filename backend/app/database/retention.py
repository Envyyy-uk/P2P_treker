"""Чисті хелпери для партиціонування і downsampling (Фаза 2.1).

Винесені окремо від виконання SQL, щоб рахуватись і тестуватись без
підключення до БД — самі запити/DDL живуть у partitioning.py /
downsampler.py.
"""

from datetime import UTC, datetime

DAY_MS = 24 * 60 * 60 * 1000
_DAY_MS = DAY_MS  # внутрішній аліас для стислості нижче


def day_bounds_ms(ts_ms: int) -> tuple[int, int]:
    """[початок доби, початок наступної доби) в UTC, в epoch ms."""
    start = (ts_ms // _DAY_MS) * _DAY_MS
    return start, start + _DAY_MS


def partition_name_for(day_start_ms: int) -> str:
    """Ім'я партиції quotes_1s для доби, що починається в day_start_ms."""
    dt = datetime.fromtimestamp(day_start_ms / 1000, tz=UTC)
    return f"quotes_1s_{dt.strftime('%Y%m%d')}"


def day_starts_in_range(from_ms: int, to_ms: int) -> list[int]:
    """Початки всіх діб у [from_ms, to_ms] (включно), відсортовані зростаюче."""
    if to_ms < from_ms:
        return []
    first = day_bounds_ms(from_ms)[0]
    last = day_bounds_ms(to_ms)[0]
    return list(range(first, last + 1, _DAY_MS))


def bucket_start_ms(ts_ms: int, bucket_ms: int) -> int:
    """Floor-бакетизація timestamp за розміром бакета (10с/1хв/5хв у ms)."""
    return (ts_ms // bucket_ms) * bucket_ms


def cutoff_ms(now_ms: int, retention_days: int) -> int:
    """Timestamp, старіший за який дані підлягають видаленню."""
    return now_ms - retention_days * _DAY_MS
