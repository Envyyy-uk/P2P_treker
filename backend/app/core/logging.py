"""Structured JSON logging з маскуванням секретів (Фаза 0.1, п.5–6)."""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

# Патерни значень, які ніколи не мають потрапити в логи у відкритому вигляді.
# Порядок важливий: Bearer маскуємо першим, інакше перший патерн з'їсть
# слово "Bearer" як значення поля authorization і токен залишиться.
_SECRET_PATTERNS = [
    # Заголовки авторизації
    re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._\-]+"),
    # key=value / "key": "value" для чутливих назв полів
    re.compile(
        r"(?i)((?:api[_-]?key|api[_-]?secret|secret|token|password|passphrase|authorization)"
        r"[\"']?\s*[=:]\s*[\"']?)([^\s\"',}]+)"
    ),
]

MASK = "***MASKED***"


def mask_secrets(text: str) -> str:
    """Замінює значення секретів у довільному тексті на маску."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(1) + MASK, text)
    return text


class SecretMaskingFilter(logging.Filter):
    """Фільтр, що маскує секрети у вже відформатованому повідомленні.

    Спершу підставляємо args (щоб маска не зламала %-плейсхолдери),
    потім маскуємо результат цілком.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_secrets(record.getMessage())
        record.args = None
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, environment: str) -> None:
        super().__init__()
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "environment": self.environment,
        }
        for extra_key in ("correlation_id", "exchange", "symbol"):
            value = getattr(record, extra_key, None)
            if value is not None:
                payload[extra_key] = value
        if record.exc_info:
            payload["exception"] = mask_secrets(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str, json_format: bool, mask: bool, environment: str) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JsonFormatter(environment))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    if mask:
        handler.addFilter(SecretMaskingFilter())
    root.addHandler(handler)
