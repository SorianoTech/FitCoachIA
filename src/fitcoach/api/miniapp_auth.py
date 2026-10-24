"""Authenticate Mini App requests using Telegram's signed launch data."""

import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException

from fitcoach.infrastructure.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def validate_init_data(raw: str, token: str, max_age: int, now: int) -> int:
    if not raw or len(raw) > 8192:
        raise ValueError("Missing or oversized launch data")
    entries = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    values = dict(entries)
    if len(entries) != len(values):
        raise ValueError("Duplicate launch fields")
    signature = values.pop("hash", "")
    if len(signature) != 64:
        raise ValueError("Missing signature")
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Invalid signature")
    issued = int(values["auth_date"])
    if issued > now + 30 or now - issued > max_age:
        raise ValueError("Expired launch data")
    user = json.loads(values["user"])
    if not isinstance(user, dict):
        raise ValueError("Missing user")
    user_id = user.get("id")
    if type(user_id) is not int or not 0 < user_id < 2**63:
        raise ValueError("Invalid user")
    return user_id


def get_miniapp_chat_id(
    init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
    settings: Settings = Depends(get_settings),
) -> int:
    try:
        return validate_init_data(
            init_data,
            settings.bot_telegram_token.get_secret_value(),
            settings.miniapp_auth_max_age_seconds,
            int(time.time()),
        )
    except (ValueError, KeyError, TypeError):
        logger.warning("Mini App authentication rejected")
        raise HTTPException(
            status_code=401, detail="Abre de nuevo la aplicación desde Telegram."
        ) from None
