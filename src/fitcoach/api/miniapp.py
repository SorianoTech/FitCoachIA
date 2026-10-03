import logging
from collections.abc import Awaitable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.api.miniapp_auth import get_miniapp_chat_id
from fitcoach.domain.workout import (
    StartWorkout,
    UpdateWorkout,
    WorkoutBootstrap,
    WorkoutConflictError,
    WorkoutNotFoundError,
    WorkoutProgress,
    WorkoutSession,
    WorkoutValidationError,
)
from fitcoach.infrastructure.database.dependencies import get_conversation_repository
from fitcoach.infrastructure.database.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.infrastructure.database.postgres_workout_repository import PostgresWorkoutRepository
from fitcoach.infrastructure.database.session import get_session
from fitcoach.service.workout_service import WorkoutService

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/miniapp", tags=["miniapp"], dependencies=[Depends(get_miniapp_chat_id)]
)
miniapp = router
T = TypeVar("T")


async def get_workout_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    conversation: Annotated[PostgresConversationRepository, Depends(get_conversation_repository)],
) -> WorkoutService:
    return WorkoutService(
        PostgresWorkoutRepository(session), conversation, PostgresTrainingRepository(session)
    )


Chat = Annotated[int, Depends(get_miniapp_chat_id)]
Service = Annotated[WorkoutService, Depends(get_workout_service)]
SessionId = Annotated[int, Path(ge=1)]


async def _respond(operation: Awaitable[T]) -> T:
    try:
        return await operation
    except WorkoutNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WorkoutConflictError as error:
        logger.warning("Mini App workout conflict: %s", error)
        raise HTTPException(status_code=409, detail=str(error)) from error
    except WorkoutValidationError as error:
        logger.warning("Mini App invalid workout: %s", error)
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/bootstrap", response_model=WorkoutBootstrap)
async def bootstrap(chat_id: Chat, service: Service) -> WorkoutBootstrap:
    return await _respond(service.bootstrap(chat_id))


@router.get("/sessions", response_model=list[WorkoutSession])
async def sessions(chat_id: Chat, service: Service) -> list[WorkoutSession]:
    return await _respond(service.list_sessions(chat_id))


@router.get("/sessions/{session_id}", response_model=WorkoutSession)
async def session_detail(session_id: SessionId, chat_id: Chat, service: Service) -> WorkoutSession:
    return await _respond(service.get(chat_id, session_id))


@router.post("/sessions", response_model=WorkoutSession)
async def start_session(request: StartWorkout, chat_id: Chat, service: Service) -> WorkoutSession:
    return await _respond(service.start(chat_id, request))


@router.patch("/sessions/{session_id}", response_model=WorkoutSession)
async def update_session(
    session_id: SessionId, patch: UpdateWorkout, chat_id: Chat, service: Service
) -> WorkoutSession:
    return await _respond(service.update(chat_id, session_id, patch))


@router.get("/progress", response_model=WorkoutProgress)
async def progress(chat_id: Chat, service: Service) -> WorkoutProgress:
    return await _respond(service.progress(chat_id))
