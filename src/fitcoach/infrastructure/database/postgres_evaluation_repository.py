import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.domain.training_evaluation import AnswerStatus
from fitcoach.infrastructure.database.models import (
    TrainingEvaluationRecord,
    TrainingMesocycleRecord,
    TrainingPlanRecord,
    TrainingSessionRecord,
)
from fitcoach.repository.evaluation_repository import PollTarget, SentPoll

logger = logging.getLogger(__name__)


class PostgresEvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def open_current_plan(self, mesocycle_id: int) -> PollTarget | None:
        row = (
            await self._session.execute(
                select(TrainingMesocycleRecord, TrainingPlanRecord)
                .join(
                    TrainingPlanRecord,
                    TrainingPlanRecord.mesocycle_id == TrainingMesocycleRecord.id,
                )
                .join(
                    TrainingSessionRecord,
                    TrainingSessionRecord.current_plan_id == TrainingPlanRecord.id,
                )
                .where(
                    TrainingMesocycleRecord.id == mesocycle_id,
                    TrainingMesocycleRecord.completed_at.is_(None),
                )
            )
        ).first()
        if row is None:
            return None
        cycle, plan = row[0], row[1]
        return PollTarget(
            mesocycle_id=cycle.id,
            started_at=cycle.started_at,
            thread_id=cycle.message_thread_id,
            plan_id=plan.id,
            goal=plan.goal,
        )

    async def previous_unanswered(self, chat_id: int) -> list[int]:
        """Message ids of the chat's polls still awaiting an answer."""
        messages = await self._session.scalars(
            select(TrainingEvaluationRecord.telegram_message_id)
            .where(
                TrainingEvaluationRecord.chat_id == chat_id,
                TrainingEvaluationRecord.answer_status == AnswerStatus.AWAITING,
                TrainingEvaluationRecord.telegram_message_id.is_not(None),
            )
            .order_by(TrainingEvaluationRecord.id)
        )
        return [message for message in messages if message is not None]

    async def save_sent(self, poll: SentPoll) -> None:
        """Close the chat's open polls and record the new one; the caller commits."""
        await self._session.execute(
            update(TrainingEvaluationRecord)
            .where(
                TrainingEvaluationRecord.chat_id == poll.chat_id,
                TrainingEvaluationRecord.answer_status == AnswerStatus.AWAITING,
            )
            .values(answer_status=AnswerStatus.UNANSWERED)
        )
        self._session.add(
            TrainingEvaluationRecord(
                chat_id=poll.chat_id,
                job_id=poll.job_id,
                plan_id=poll.target.plan_id,
                mesocycle_id=poll.target.mesocycle_id,
                goal=poll.target.goal,
                week_number=poll.week_number,
                answer_status=AnswerStatus.AWAITING,
                telegram_poll_id=poll.poll_id,
                telegram_message_id=poll.message_id,
                sent_at=poll.sent_at,
            )
        )
        await self._session.flush()

    async def record_answer(
        self, poll_id: str, user_id: int, score: int | None, now: datetime
    ) -> bool:
        record = await self._session.scalar(
            select(TrainingEvaluationRecord)
            .where(TrainingEvaluationRecord.telegram_poll_id == poll_id)
            .with_for_update()
        )
        # Private chats only: the chat id is the owner's user id.
        if record is None or record.chat_id != user_id:
            await self._session.commit()
            return False
        if record.answer_status == AnswerStatus.UNANSWERED:
            logger.info("Late vote on closed poll %s of chat %s ignored", poll_id, record.chat_id)
            await self._session.commit()
            return False
        record.score = score
        record.answered_at = now if score is not None else None
        record.answer_status = AnswerStatus.ANSWERED if score is not None else AnswerStatus.AWAITING
        await self._session.commit()
        return True
