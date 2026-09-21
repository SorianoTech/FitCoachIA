"""Verifica que el webhook lo llama Telegram y no un tercero."""

import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from fitcoach.infrastructure.config.settings import Settings, get_settings


async def verify_telegram_secret(
    settings: Annotated[Settings, Depends(get_settings)],
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.bot_telegram_secret_token.get_secret_value().encode()
    received = (x_telegram_bot_api_secret_token or "").encode()
    # compare_digest: tiempo constante, no se deduce el secreto midiendo respuestas.
    if not received or not hmac.compare_digest(received, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
