import json
import logging

from app.core.logging import (
    MASK,
    JsonFormatter,
    SecretMaskingFilter,
    mask_secrets,
)


class TestMaskSecrets:
    def test_masks_api_key_assignment(self):
        assert "SECRETVALUE" not in mask_secrets("api_key=SECRETVALUE123")

    def test_masks_json_style(self):
        assert "sk-abc" not in mask_secrets('{"api_secret": "sk-abc123"}')

    def test_masks_bearer_token(self):
        masked = mask_secrets("Authorization: Bearer eyJhbGciOi.abc-123")
        assert "eyJhbGciOi" not in masked
        assert MASK in masked

    def test_masks_passphrase(self):
        assert "hunter2" not in mask_secrets("passphrase='hunter2'")

    def test_leaves_normal_text(self):
        text = "spread BTC-USDT binance->bybit net=0.0012"
        assert mask_secrets(text) == text


def test_filter_masks_record_and_args():
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="connecting with api_key=%s",
        args=("api_key=REALKEY",),
        exc_info=None,
    )
    SecretMaskingFilter().filter(record)
    assert "REALKEY" not in record.getMessage()


def test_json_formatter_output_is_valid_json():
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="hello",
        args=(),
        exc_info=None,
    )
    payload = json.loads(JsonFormatter("dev").format(record))
    assert payload["message"] == "hello"
    assert payload["environment"] == "dev"
    assert payload["level"] == "INFO"
