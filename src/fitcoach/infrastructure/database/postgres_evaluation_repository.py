from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.domain.training_evaluation import EvaluationState, due_week, upcoming_polls
from fitcoach.infrastructure.database.models import (
    TrainingEvaluationRecord,
    TrainingMesocycleRecord,
    TrainingPlanRecord,
    TrainingSessionRecord,
)
from fitcoach.repository.evaluation_repository import EvaluationConflictError, EvaluationDelivery

_CLAIMABLE = (EvaluationState.PENDING, EvaluationState.SENDING)


async def schedule_evaluations(
    session: AsyncSession, cycle: TrainingMesocycleRecord, now: datetime
) -> None:
    """Queue the weekly polls of a dated cycle inside the caller's transaction."""
    if cycle.started_at is None:
        return
    rows = [
        {"chat_id": cycle.chat_id, "mesocycle_id": cycle.id, "week_number": week, "due_at": due}
        for week, due in upcoming_polls(cycle.started_at, now)
    ]
    if rows:
        await session.execute(
            insert(TrainingEvaluationRecord)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_training_evaluation_cycle_week")
        )


async def cancel_pending_evaluations(session: AsyncSession, *criteria: ColumnElement[bool]) -> None:
    """Drop polls not yet claimed; one already being sent finishes and stays recorded."""
    await session.execute(
        update(TrainingEvaluationRecord)
        .where(TrainingEvaluationRecord.state == EvaluationState.PENDING, *criteria)
        .values(state=EvaluationState.CANCELLED)
    )


class PostgresEvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(self, now: datetime, sending_timeout: timedelta) -> EvaluationDelivery | None:
        while True:
            record = await self._session.scalar(
                select(TrainingEvaluationRecord)
                .where(
                    TrainingEvaluationRecord.state.in_(_CLAIMABLE),
                    TrainingEvaluationRecord.due_at <= now,
                    TrainingEvaluationRecord.locked_until.is_(None)
                    | (TrainingEvaluationRecord.locked_until <= now),
                )
                .order_by(TrainingEvaluationRecord.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                await self._session.commit()
                return None
            current = await self._open_current_plan(record.mesocycle_id)
            if current is None or self._superseded(record, current[0], now):
                record.state = EvaluationState.CANCELLED
                record.locked_until = None
                await self._session.commit()
                continue
            cycle, plan = current
            record.plan_id = plan.id
            record.goal = plan.goal
            record.state = EvaluationState.SENDING
            record.locked_until = now + sending_timeout
            record.attempts += 1
            delivery = EvaluationDelivery(
                id=record.id,
                chat_id=record.chat_id,
                thread_id=cycle.message_thread_id,
                week_number=record.week_number,
                goal=plan.goal,
                attempts=record.attempts,
                previous_message_id=await self._previous_unanswered(record),
            )
            await self._session.commit()
            return delivery

    async def mark_sent(
        self, delivery: EvaluationDelivery, poll_id: str, message_id: int, now: datetime
    ) -> None:
        record = await self._owned(delivery)
        record.state = EvaluationState.SENT
        record.locked_until = None
        record.telegram_poll_id = poll_id
        record.telegram_message_id = message_id
        record.sent_at = now
        await self._session.commit()

    async def finish(
        self, delivery: EvaluationDelivery, retry_at: datetime | None = None, failed: bool = False
    ) -> None:
        record = await self._owned(delivery)
        if failed:
            record.state = EvaluationState.FAILED
        else:
            record.state = EvaluationState.PENDING
            if retry_at is not None:
                record.due_at = retry_at
        record.locked_until = None
        await self._session.commit()

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
        record.score = score
        record.answered_at = now if score is not None else None
        await self._session.commit()
        return True

    @staticmethod
    def _superseded(
        record: TrainingEvaluationRecord, cycle: TrainingMesocycleRecord, now: datetime
    ) -> bool:
        """A newer week is already due: only the most recent one is asked."""
        if cycle.started_at is None:
            return True
        return (due_week(cycle.started_at, now) or 0) > record.week_number

    async def _open_current_plan(
        self, mesocycle_id: int | None
    ) -> tuple[TrainingMesocycleRecord, TrainingPlanRecord] | None:
        if mesocycle_id is None:
            return None
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
        return None if row is None else (row[0], row[1])

    async def _previous_unanswered(self, record: TrainingEvaluationRecord) -> int | None:
        previous = await self._session.scalar(
            select(TrainingEvaluationRecord)
            .where(
                TrainingEvaluationRecord.mesocycle_id == record.mesocycle_id,
                TrainingEvaluationRecord.week_number < record.week_number,
                TrainingEvaluationRecord.state == EvaluationState.SENT,
            )
            .order_by(TrainingEvaluationRecord.week_number.desc())
            .limit(1)
        )
        if previous is None or previous.score is not None:
            return None
        return previous.telegram_message_id

    async def _owned(self, delivery: EvaluationDelivery) -> TrainingEvaluationRecord:
        record = await self._session.scalar(
            select(TrainingEvaluationRecord)
            .where(TrainingEvaluationRecord.id == delivery.id)
            .with_for_update()
        )
        if (
            record is None
            or record.state != EvaluationState.SENDING
            or record.attempts != delivery.attempts
        ):
            await self._session.rollback()
            raise EvaluationConflictError(f"Evaluation {delivery.id} is no longer locked")
        return record
