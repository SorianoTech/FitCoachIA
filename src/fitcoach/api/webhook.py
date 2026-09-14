"""Telegram webhook controller: receive updates and delegate to the service layer."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from telegram import Bot, Update

from fitcoach.infrastructure.bot.telegram_bot import get_bot
from fitcoach.infrastructure.config.settings import IASettings, get_ia_settings
from fitcoach.infrastructure.database.dependencies import get_conversation_repository
from fitcoach.infrastructure.database.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from fitcoach.service.agent.interviewer_chain import InterviewerChain, get_interviewer_chain
from fitcoach.service.conversation_service import ConversationService

logger = logging.getLogger(__name__)

webhook = APIRouter(prefix="/webhook", tags=["telegram"])


async def parse_update(request: Request) -> Update:
    """Build a ``telegram.Update`` from the raw webhook body.

    FastAPI can only auto-bind Pydantic models, and ``telegram.Update`` is not
    one, so we read the raw JSON body and hand back a real library object.
    """
    try:
        data = await request.json()
    except ValueError as exc:
        logger.warning(f"Malformed webhook body received: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON body",
        ) from exc
    return Update.de_json(data)


def get_conversation_service(
    bot: Bot = Depends(get_bot),
    interviewer: InterviewerChain = Depends(get_interviewer_chain),
    repository: PostgresConversationRepository = Depends(get_conversation_repository),
    ia_settings: IASettings = Depends(get_ia_settings),
) -> ConversationService:
    return ConversationService(
        bot=bot,
        interviewer=interviewer,
        conversation_repository=repository,
        history_window_messages=ia_settings.history_window_messages,
    )


@webhook.post("/response")
async def telegram_webhook(
    update: Update = Depends(parse_update),
    service: ConversationService = Depends(get_conversation_service),
) -> dict[str, bool]:
    # ``handle_update`` no propaga excepciones: Telegram reenvia cualquier
    # update que no reciba un 2xx, asi que siempre se responde 200.
    await service.handle_update(update)
    return {"ok": True}
