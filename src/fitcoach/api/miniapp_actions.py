"""Mini App handoff to existing confirmed Telegram training workflows."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import TelegramError

from fitcoach.api.miniapp_auth import get_miniapp_chat_id
from fitcoach.api.webhook import get_training_service
from fitcoach.infrastructure.bot.telegram_bot import get_bot
from fitcoach.infrastructure.database.dependencies import get_conversation_repository
from fitcoach.infrastructure.database.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.infrastructure.database.session import get_session
from fitcoach.service.training_service import TrainingService
from fitcoach.service.typing_indicator import typing_indicator

logger = logging.getLogger(__name__)
miniapp_actions = APIRouter(
    prefix="/api/miniapp", tags=["miniapp"], dependencies=[Depends(get_miniapp_chat_id)]
)


class TrainingAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: int = Field(gt=0)
    action: Literal["swap", "review"]


@miniapp_actions.post("/actions")
async def open_training_action(
    action: TrainingAction,
    chat_id: int = Depends(get_miniapp_chat_id),
    conversation: PostgresConversationRepository = Depends(get_conversation_repository),
    session: AsyncSession = Depends(get_session),
    service: TrainingService = Depends(get_training_service),
    bot: Bot = Depends(get_bot),
) -> dict[str, str]:
    stored = await conversation.get_current_plan(chat_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="No tienes un plan activo.")
    if stored.id != action.plan_id:
        logger.warning("Mini App action rejected: stale plan")
        raise HTTPException(status_code=409, detail="El plan ha cambiado. Recarga la aplicación.")
    workflow = await PostgresTrainingRepository(session).get_workflow(chat_id)
    kind = "exercise_swap" if action.action == "swap" else "renewal"
    if workflow and workflow.kind != kind:
        raise HTTPException(
            status_code=409, detail="Continúa o cancela primero la propuesta pendiente en el chat."
        )
    try:
        me = await bot.get_me()
        if not me.username:
            raise HTTPException(status_code=503, detail="El bot no tiene un nombre configurado.")
        async with typing_indicator(bot, chat_id):
            responses = await service.handle(
                chat_id, "/train cambiar" if action.action == "swap" else "/train revisar"
            )
        keyboard = await service.keyboard(chat_id, responses)
        for index, text in enumerate(responses):
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard if index == len(responses) - 1 else None,
            )
    except TelegramError:
        logger.exception("Mini App Telegram handoff delivery failed")
        raise HTTPException(
            status_code=502, detail="No se pudo enviar al chat. Reintenta o abre /train."
        ) from None
    return {
        "message": "Continúa en el chat: los cambios requieren tu confirmación.",
        "bot_url": f"https://t.me/{me.username}",
    }
