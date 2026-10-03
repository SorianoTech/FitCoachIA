import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from fitcoach.api.miniapp_auth import get_miniapp_chat_id, validate_init_data
from fitcoach.infrastructure.config.settings import Settings

TOKEN = "miniapp-test-token"  # noqa: S105
NOW = 1791060000


def signed(fields: dict[str, str]) -> str:
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": signature})


def settings(**values: object) -> Settings:
    return Settings(
        _env_file=None,
        bot_telegram_token=TOKEN,
        bot_telegram_url="https://api.telegram.org/bot",
        bot_telegram_commands=["train:Entrenamiento"],
        bot_telegram_secret_token="secret",  # noqa: S106
        bot_telegram_webhook_base_url="https://example.com",
        **values,
    )


def test_signed_user_identity_not_untrusted_chat_id() -> None:
    raw = signed({
        "auth_date": str(NOW),
        "user": json.dumps({"id": 99}),
        "chat": json.dumps({"id": 1234}),
    })
    assert validate_init_data(raw, TOKEN, 3600, NOW) == 99


@pytest.mark.parametrize(
    "fields",
    [
        {"auth_date": str(NOW - 3601), "user": '{"id":99}'},
        {"auth_date": str(NOW + 31), "user": '{"id":99}'},
        {"auth_date": "invalid", "user": '{"id":99}'},
        {"auth_date": str(NOW), "user": '{"id":true}'},
        {"auth_date": str(NOW), "user": '{"id":-1}'},
        {"auth_date": str(NOW), "user": '{"id":1.5}'},
        {"auth_date": str(NOW), "user": '{"id":9223372036854775808}'},
        {"auth_date": str(NOW), "user": '["id",99]'},
        {"auth_date": str(NOW), "user": "not-json"},
    ],
)
def test_rejects_signed_invalid_launch_fields(fields: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=".+"):
        validate_init_data(signed(fields), TOKEN, 3600, NOW)


def test_rejects_tampered_wrong_bot_duplicate_and_missing_launch_data() -> None:
    raw = signed({"auth_date": str(NOW), "user": '{"id":99}'})
    for invalid in ("", raw + "&auth_date=0", raw.replace("99", "88"), "broken", "x" * 8193):
        with pytest.raises(ValueError, match=".+"):
            validate_init_data(invalid, TOKEN, 3600, NOW)
    with pytest.raises(ValueError, match="Invalid signature"):
        validate_init_data(raw, "different-bot", 3600, NOW)


def test_dependency_returns_401_without_sensitive_detail() -> None:
    with pytest.raises(HTTPException) as error:
        get_miniapp_chat_id("invalid", settings())
    assert error.value.status_code == 401
    assert TOKEN not in error.value.detail


def test_miniapp_config_is_optional_and_accepts_https() -> None:
    assert settings(miniapp_url="").miniapp_url is None
    assert settings(miniapp_url="https://example.com/miniapp/").miniapp_url


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/miniapp/",
        "https://example.com/other/",
        "https://example.com/miniapp/?token=value",
        "https://example.com/miniapp/#value",
        "https://user:password@example.com/miniapp/",
    ],
)
def test_miniapp_rejects_insecure_or_credential_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        settings(miniapp_url=url)
