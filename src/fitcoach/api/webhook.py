"""Telegram webhook controller: receive updates and delegate to the service layer."""

import logging
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot, Update

from fitcoach.api.admin import get_quota_service
from fitcoach.api.security import verify_telegram_secret
from fitcoach.infrastructure.bot.telegram_bot import get_bot
from fitcoach.infrastructure.config.settings import (
    IASettings,
    Settings,
    UsageSettings,
    get_ia_settings,
    get_settings,
    get_training_settings,
    get_usage_settings,
)
from fitcoach.infrastructure.database.dependencies import get_conversation_repository
from fitcoach.infrastructure.database.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from fitcoach.infrastructure.database.postgres_exercise_submission_repository import (
    PostgresExerciseSubmissionRepository,
)
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.infrastructure.database.postgres_workout_repository import PostgresWorkoutRepository
from fitcoach.infrastructure.database.session import get_session
from fitcoach.infrastructure.ia.embedder_client import EmbedderClient, get_embedder_client
from fitcoach.infrastructure.vectordb.pgvector_exercise_publisher import (
    PgVectorExercisePublisher,
)
from fitcoach.infrastructure.vectordb.pgvector_exercise_repository import (
    PgVectorExerciseRepository,
)
from fitcoach.infrastructure.vectordb.session import (
    get_vector_session,
    get_vector_writer_session,
)
from fitcoach.service.agent.exercise_curator_chain import (
    ExerciseCuratorChain,
    get_exercise_curator_chain,
)
from fitcoach.service.agent.exercise_duplicate_detector import ExerciseDuplicateDetector
from fitcoach.service.agent.exercise_retriever import ExerciseRetriever
from fitcoach.service.agent.interviewer_chain import InterviewerChain, get_interviewer_chain
from fitcoach.service.agent.trainer_chain import TrainerChain, get_trainer_chain
from fitcoach.service.agent.training_adaptation_chain import (
    TrainingAdaptationChain,
    get_training_adaptation_chain,
)
from fitcoach.service.conversation_service import ConversationService
from fitcoach.service.exercise_moderation_service import ExerciseModerationService
from fitcoach.service.exercise_submission_service import ExerciseSubmissionService
from fitcoach.service.quota_service import QuotaService
from fitcoach.service.training_service import TrainingService

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
    embedder: EmbedderClient
    exercise_repository: PgVectorExerciseRepository


def get_trainer_deps(
    trainer: TrainerChain = Depends(get_trainer_chain),
    embedder: EmbedderClient = Depends(get_embedder_client),
    vector_session: AsyncSession = Depends(get_vector_session),
    ia_settings: IASettings = Depends(get_ia_settings),
) -> TrainerDeps:
    exercise_repository = PgVectorExerciseRepository(vector_session)
    return TrainerDeps(
        chain=trainer,
        retriever=ExerciseRetriever(
            embedder=embedder,
            exercise_repository=exercise_repository,
            top_k=ia_settings.rag_top_k,
        ),
        embedder=embedder,
        exercise_repository=exercise_repository,
    )


def get_exercise_submission_service(
    curator: ExerciseCuratorChain = Depends(get_exercise_curator_chain),
    session: AsyncSession = Depends(get_session),
    trainer_deps: TrainerDeps = Depends(get_trainer_deps),
    ia_settings: IASettings = Depends(get_ia_settings),
) -> ExerciseSubmissionService:
    return ExerciseSubmissionService(
        curator,
        PostgresExerciseSubmissionRepository(session),
        ExerciseDuplicateDetector(
            trainer_deps.embedder,
            trainer_deps.exercise_repository,
            ia_settings.exercise_duplicate_similarity_threshold,
        ),
        ia_settings.exercise_curator_model,
    )


def get_exercise_moderation_service(
    session: AsyncSession = Depends(get_session),
    vector_writer_session: AsyncSession | None = Depends(get_vector_writer_session),
    embedder: EmbedderClient = Depends(get_embedder_client),
    settings: Settings = Depends(get_settings),
) -> ExerciseModerationService:
    publisher = (
        PgVectorExercisePublisher(vector_writer_session)
        if vector_writer_session is not None
        else None
    )
    return ExerciseModerationService(
        PostgresExerciseSubmissionRepository(session),
        embedder,
        publisher,
        set(settings.bot_telegram_exercise_admin_ids),
    )


def get_conversation_service(
    bot: Bot = Depends(get_bot),
    interviewer: InterviewerChain = Depends(get_interviewer_chain),
    repository: PostgresConversationRepository = Depends(get_conversation_repository),
    ia_settings: IASettings = Depends(get_ia_settings),
    trainer_deps: TrainerDeps = Depends(get_trainer_deps),
    usage_settings: UsageSettings = Depends(get_usage_settings),
    session: AsyncSession = Depends(get_session),
    adaptation: TrainingAdaptationChain = Depends(get_training_adaptation_chain),
    quotas: QuotaService = Depends(get_quota_service),
    exercise_submissions: ExerciseSubmissionService = Depends(get_exercise_submission_service),
    exercise_moderation: ExerciseModerationService = Depends(get_exercise_moderation_service),
) -> ConversationService:
    return ConversationService(
        bot=bot,
        interviewer=interviewer,
        conversation_repository=repository,
        usage_limits=usage_settings.to_limits(),
        quota_resolver=quotas.resolve,
        history_window_messages=ia_settings.history_window_messages,
        trainer=trainer_deps.chain,
        exercise_retriever=trainer_deps.retriever,
        trainer_history_window_messages=ia_settings.trainer_history_window_messages,
        training_service=get_training_service(
            repository, trainer_deps, usage_settings, session, adaptation, quotas
        ),
        exercise_submissions=exercise_submissions,
        exercise_moderation=exercise_moderation,
    )


def get_training_service(
    repository: PostgresConversationRepository = Depends(get_conversation_repository),
    trainer_deps: TrainerDeps = Depends(get_trainer_deps),
    usage_settings: UsageSettings = Depends(get_usage_settings),
    session: AsyncSession = Depends(get_session),
    adaptation: TrainingAdaptationChain = Depends(get_training_adaptation_chain),
    quotas: QuotaService = Depends(get_quota_service),
) -> TrainingService:
    return TrainingService(
        PostgresTrainingRepository(session),
        repository,
        trainer_deps.chain,
        trainer_deps.retriever,
        adaptation,
        usage_settings.to_limits(),
        reminder_max_attempts=get_training_settings().reminder_max_attempts,
        miniapp_url=get_settings().miniapp_url,
        performance_summary=PostgresWorkoutRepository(session).performance_summary,
        quota_resolver=quotas.resolve,
    )


@webhook.post("/response", dependencies=[Depends(verify_telegram_secret)])
async def telegram_webhook(
    update: Update = Depends(parse_update),
    service: ConversationService = Depends(get_conversation_service),
) -> dict[str, bool]:
    # ``handle_update`` no propaga excepciones: Telegram reenvia cualquier
    # update que no reciba un 2xx, asi que siempre se responde 200.
    await service.handle_update(update)
    return {"ok": True}
