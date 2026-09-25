"""Telegram webhook controller: receive updates and delegate to the service layer."""

import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot, Update

from fitcoach.infrastructure.bot.telegram_bot import get_bot
from fitcoach.infrastructure.config.settings import IASettings, get_ia_settings
from fitcoach.infrastructure.database.dependencies import get_conversation_repository
from fitcoach.infrastructure.database.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from fitcoach.infrastructure.ia.embedder_client import EmbedderClient, get_embedder_client
from fitcoach.infrastructure.vectordb.pgvector_exercise_repository import (
    PgVectorExerciseRepository,
)
from fitcoach.infrastructure.vectordb.session import get_vector_session
from fitcoach.service.agent.exercise_retriever import ExerciseRetriever
from fitcoach.service.agent.interviewer_chain import InterviewerChain, get_interviewer_chain
from fitcoach.service.agent.trainer_chain import TrainerChain, get_trainer_chain
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


@dataclass(frozen=True, slots=True)
class TrainerDeps:
    """The Trainer's collaborators, grouped so the service factory stays readable."""

    chain: TrainerChain
    retriever: ExerciseRetriever


def get_trainer_deps(
    trainer: TrainerChain = Depends(get_trainer_chain),
    embedder: EmbedderClient = Depends(get_embedder_client),
    vector_session: AsyncSession = Depends(get_vector_session),
    ia_settings: IASettings = Depends(get_ia_settings),
) -> TrainerDeps:
    return TrainerDeps(
        chain=trainer,
        retriever=ExerciseRetriever(
            embedder=embedder,
            exercise_repository=PgVectorExerciseRepository(vector_session),
            top_k=ia_settings.rag_top_k,
        ),
    )


def get_conversation_service(
    bot: Bot = Depends(get_bot),
    interviewer: InterviewerChain = Depends(get_interviewer_chain),
    repository: PostgresConversationRepository = Depends(get_conversation_repository),
    ia_settings: IASettings = Depends(get_ia_settings),
    trainer_deps: TrainerDeps = Depends(get_trainer_deps),
) -> ConversationService:
    return ConversationService(
        bot=bot,
        interviewer=interviewer,
        conversation_repository=repository,
        history_window_messages=ia_settings.history_window_messages,
        trainer=trainer_deps.chain,
        exercise_retriever=trainer_deps.retriever,
        trainer_history_window_messages=ia_settings.trainer_history_window_messages,
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
