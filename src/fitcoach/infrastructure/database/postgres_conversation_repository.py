import json
import logging
from decimal import Decimal
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.domain.agents import AgentType
from fitcoach.domain.conversation import ConversationMessage
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.trainer_plan import TRAINING_STATUS_ACTIVE, TrainingPlan
from fitcoach.infrastructure.database.models import (
    ConversationMessageRecord,
    InterviewerProfileRecord,
    InterviewSessionRecord,
    ModelPriceRecord,
    TokenUsageRecord,
    TrainingPlanRecord,
    TrainingSessionRecord,
)
from fitcoach.repository.conversation_repository import StoredTrainingPlan

logger = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


def _validate_stored(model: type[ModelT], stored: object) -> ModelT:
    """Re-validate a JSON column through JSON, not through Python objects.

    The domain models are ``strict=True``. In Python mode that rejects the ISO
    strings a ``model_dump(mode="json")`` round-trip produces for datetimes;
    in JSON mode Pydantic applies its documented string coercions. Going back
    through ``json.dumps`` keeps the models strict without making storage
    round-trips fail.
    """
    return model.model_validate_json(json.dumps(stored))


class PostgresConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_recent(
        self,
        chat_id: int,
        limit: int,
        agent: str = AgentType.INTERVIEWER.value,
    ) -> list[ConversationMessage]:
        statement = (
            select(ConversationMessageRecord)
            .where(
                ConversationMessageRecord.chat_id == chat_id,
                ConversationMessageRecord.agent == agent,
            )
            .order_by(ConversationMessageRecord.id.desc())
            .limit(limit)
        )
        records = list((await self._session.scalars(statement)).all())
        return [
            ConversationMessage(
                chat_id=record.chat_id,
                role=record.role,
                content=record.content,
                created_at=record.created_at,
            )
            for record in reversed(records)
        ]

    async def add_turn(
        self,
        chat_id: int,
        user_content: str,
        assistant_content: str,
        agent: str = AgentType.INTERVIEWER.value,
    ) -> int:
        assistant_message = ConversationMessageRecord(
            chat_id=chat_id,
            agent=agent,
            role="assistant",
            content=assistant_content,
        )
        self._session.add_all([
            ConversationMessageRecord(
                chat_id=chat_id, agent=agent, role="user", content=user_content
            ),
            assistant_message,
        ])
        await self._session.commit()
        return assistant_message.id

    async def get_interview_status(self, chat_id: int) -> str | None:
        status = await self._session.scalar(
            select(InterviewSessionRecord.status).where(InterviewSessionRecord.chat_id == chat_id)
        )
        return status if isinstance(status, str) else None

    async def restart_interview(self, chat_id: int) -> None:
        """Wipe the chat's history, profile and plan, then open a new session.

        The plan goes too: it was derived from the profile being replaced, so
        leaving it behind would hand the user a mesocycle built for someone they
        no longer are.
        """
        await self._session.execute(
            delete(ConversationMessageRecord).where(ConversationMessageRecord.chat_id == chat_id)
        )
        await self._session.execute(
            delete(TrainingSessionRecord).where(TrainingSessionRecord.chat_id == chat_id)
        )
        await self._session.execute(
            delete(TrainingPlanRecord).where(TrainingPlanRecord.chat_id == chat_id)
        )
        await self._session.execute(
            delete(InterviewerProfileRecord).where(InterviewerProfileRecord.chat_id == chat_id)
        )
        await self._session.execute(
            delete(InterviewSessionRecord).where(InterviewSessionRecord.chat_id == chat_id)
        )
        self._session.add(InterviewSessionRecord(chat_id=chat_id, status="in_progress"))
        await self._session.commit()

    async def complete_interview(
        self,
        chat_id: int,
        user_content: str,
        assistant_content: str,
        profile: InterviewerProfile,
        report: str,
    ) -> int:
        assistant_message = ConversationMessageRecord(
            chat_id=chat_id,
            agent=AgentType.INTERVIEWER.value,
            role="assistant",
            content=assistant_content,
        )
        self._session.add_all([
            ConversationMessageRecord(
                chat_id=chat_id,
                agent=AgentType.INTERVIEWER.value,
                role="user",
                content=user_content,
            ),
            assistant_message,
            InterviewerProfileRecord(
                chat_id=chat_id,
                profile=profile.model_dump(mode="json"),
                report=report,
            ),
        ])
        session = await self._session.get(InterviewSessionRecord, chat_id)
        if session is None:
            session = InterviewSessionRecord(chat_id=chat_id, status="completed")
            self._session.add(session)
        else:
            session.status = "completed"
        session.completed_at = func.now()
        await self._session.commit()
        return assistant_message.id

    async def get_interviewer_profile(self, chat_id: int) -> InterviewerProfile | None:
        record = await self._session.get(InterviewerProfileRecord, chat_id)
        if record is None:
            return None
        try:
            return _validate_stored(InterviewerProfile, record.profile)
        except ValidationError:
            # A stored profile that no longer satisfies the model means the
            # schema moved on. Treat it as absent -- the user is told to redo
            # the interview rather than getting a plan built on garbage -- but
            # log it: this is a data problem, not a normal "no profile yet".
            logger.exception("Stored profile for chat %s no longer validates", chat_id)
            return None

    async def get_training_status(self, chat_id: int) -> str | None:
        status = await self._session.scalar(
            select(TrainingSessionRecord.status).where(TrainingSessionRecord.chat_id == chat_id)
        )
        return status if isinstance(status, str) else None

    async def get_current_plan(self, chat_id: int) -> StoredTrainingPlan | None:
        statement = (
            select(TrainingPlanRecord)
            .where(TrainingPlanRecord.chat_id == chat_id)
            .order_by(TrainingPlanRecord.version.desc())
            .limit(1)
        )
        record = (await self._session.scalars(statement)).first()
        if record is None:
            return None
        try:
            plan = _validate_stored(TrainingPlan, record.plan)
        except ValidationError:
            logger.exception("Stored plan %s for chat %s no longer validates", record.id, chat_id)
            return None
        return StoredTrainingPlan(
            id=record.id, version=record.version, plan=plan, report=record.report
        )

    async def save_training_plan(
        self,
        chat_id: int,
        plan: TrainingPlan,
        report: str,
        user_content: str,
        assistant_content: str,
    ) -> int:
        """Append version N+1 and point the session at it. Older plans are kept."""
        current_version = await self._session.scalar(
            select(func.max(TrainingPlanRecord.version)).where(
                TrainingPlanRecord.chat_id == chat_id
            )
        )
        plan_record = TrainingPlanRecord(
            chat_id=chat_id,
            version=(current_version or 0) + 1,
            plan=plan.model_dump(mode="json"),
            report=report,
        )
        assistant_message = ConversationMessageRecord(
            chat_id=chat_id,
            agent=AgentType.TRAINER.value,
            role="assistant",
            content=assistant_content,
        )
        self._session.add_all([
            ConversationMessageRecord(
                chat_id=chat_id,
                agent=AgentType.TRAINER.value,
                role="user",
                content=user_content,
            ),
            assistant_message,
            plan_record,
        ])
        # The session row needs the plan's id, which only exists after a flush.
        await self._session.flush()

        training_session = await self._session.get(TrainingSessionRecord, chat_id)
        if training_session is None:
            training_session = TrainingSessionRecord(
                chat_id=chat_id,
                status=TRAINING_STATUS_ACTIVE,
                current_plan_id=plan_record.id,
            )
            self._session.add(training_session)
        else:
            training_session.status = TRAINING_STATUS_ACTIVE
            training_session.current_plan_id = plan_record.id
        training_session.updated_at = func.now()
        await self._session.commit()
        return assistant_message.id

    async def record_token_usage(
        self,
        chat_id: int,
        agent: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        latency_ms: int,
        status: str,
        conversation_message_id: int | None,
    ) -> None:
        price = await self._session.get(ModelPriceRecord, model)
        cost_usd = None
        if price is not None:
            cost_usd = (
                (
                    Decimal(prompt_tokens) * Decimal(str(price.input_usd_per_million))
                    + Decimal(completion_tokens) * Decimal(str(price.output_usd_per_million))
                )
                / Decimal(1_000_000)
            ).quantize(Decimal("0.000001"))
        self._session.add(
            TokenUsageRecord(
                chat_id=chat_id,
                agent=agent,
                model=model,
                conversation_message_id=conversation_message_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                status=status,
                cost_usd=cost_usd,
            )
        )
        await self._session.commit()
