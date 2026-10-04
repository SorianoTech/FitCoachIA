import json
from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.training_lifecycle import (
    Mesocycle,
    TrainingWorkflow,
    expected_end,
    utc_now,
)
from fitcoach.infrastructure.database.models import (
    TrainingMesocycleRecord,
    TrainingNotificationRecord,
    TrainingPlanRecord,
    TrainingSessionRecord,
    TrainingWorkflowRecord,
)
from fitcoach.infrastructure.observability.latency import timed
from fitcoach.repository.training_repository import ReminderDelivery, TrainingConflictError

_OPEN = ("reviewing", "generating", "awaiting_confirmation")


class PostgresTrainingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _lock(self, chat_id: int) -> None:
        await self._session.execute(select(func.pg_advisory_xact_lock(chat_id)))

    async def _cycle_record(self, chat_id: int) -> TrainingMesocycleRecord | None:
        return await self._session.scalar(
            select(TrainingMesocycleRecord)
            .join(TrainingPlanRecord, TrainingPlanRecord.mesocycle_id == TrainingMesocycleRecord.id)
            .join(
                TrainingSessionRecord,
                TrainingSessionRecord.current_plan_id == TrainingPlanRecord.id,
            )
            .where(TrainingSessionRecord.chat_id == chat_id, TrainingPlanRecord.chat_id == chat_id)
            .execution_options(populate_existing=True)
        )

    async def get_cycle(self, chat_id: int) -> Mesocycle | None:
        record = await self._cycle_record(chat_id)
        if record is None:
            return None
        return Mesocycle(
            id=record.id,
            started_at=record.started_at,
            expected_end_at=record.expected_end_at,
            completed_at=record.completed_at,
            reminders_enabled=record.reminders_enabled,
        )

    async def get_workflow(self, chat_id: int) -> TrainingWorkflow | None:
        record = await self._session.scalar(
            select(TrainingWorkflowRecord)
            .where(
                TrainingWorkflowRecord.chat_id == chat_id, TrainingWorkflowRecord.state.in_(_OPEN)
            )
            .execution_options(populate_existing=True)
        )
        return self._decode(record) if record else None

    @staticmethod
    def _decode(record: TrainingWorkflowRecord) -> TrainingWorkflow:
        return TrainingWorkflow.model_validate_json(json.dumps(record.payload))

    async def start(
        self, chat_id: int, kind: Literal["renewal", "exercise_swap"]
    ) -> TrainingWorkflow:
        await self._lock(chat_id)
        existing = await self.get_workflow(chat_id)
        if existing:
            await self._session.commit()
            return existing
        session = await self._session.get(TrainingSessionRecord, chat_id, populate_existing=True)
        if session is None or session.current_plan_id is None:
            raise TrainingConflictError("No active training plan")
        workflow = TrainingWorkflow(
            id=0,
            kind=kind,
            base_plan_id=session.current_plan_id,
            state="reviewing",
        )
        record = TrainingWorkflowRecord(
            chat_id=chat_id,
            base_plan_id=session.current_plan_id,
            state=workflow.state,
            payload=workflow.model_dump(mode="json"),
        )
        self._session.add(record)
        await self._session.flush()
        workflow.id = record.id
        record.payload = workflow.model_dump(mode="json")
        await self._session.commit()
        return workflow

    @timed("persistence")
    async def save(self, chat_id: int, workflow: TrainingWorkflow) -> TrainingWorkflow:
        await self._lock(chat_id)
        record = await self._session.get(
            TrainingWorkflowRecord, workflow.id, populate_existing=True
        )
        if record is None or record.chat_id != chat_id:
            raise TrainingConflictError("Unknown proposal")
        current = self._decode(record)
        if current.revision != workflow.revision or current.state not in _OPEN:
            raise TrainingConflictError("Proposal changed concurrently")
        session = await self._session.get(TrainingSessionRecord, chat_id, populate_existing=True)
        if session is None or session.current_plan_id != workflow.base_plan_id:
            record.state = "stale"
            current.state = "stale"
            record.payload = current.model_dump(mode="json")
            await self._session.commit()
            raise TrainingConflictError("Base plan is no longer current")
        workflow.revision += 1
        record.state = workflow.state
        record.payload = workflow.model_dump(mode="json")
        await self._session.commit()
        return workflow

    async def claim_generation(self, chat_id: int, workflow_id: int) -> TrainingWorkflow:
        await self._lock(chat_id)
        workflow = await self.get_workflow(chat_id)
        now = utc_now()
        if workflow is None or workflow.id != workflow_id:
            raise TrainingConflictError("Unknown proposal")
        if workflow.state == "generating" and workflow.lease_until and workflow.lease_until > now:
            raise TrainingConflictError("Generation already running")
        workflow.state = "generating"
        workflow.lease_until = now + timedelta(minutes=15)
        workflow.generation_key = str(uuid4())
        return await self.save(chat_id, workflow)

    @timed("activation")
    async def accept(
        self, chat_id: int, workflow_id: int, start: datetime, expected_revision: int | None = None
    ) -> int:
        await self._lock(chat_id)
        record = await self._session.get(
            TrainingWorkflowRecord, workflow_id, populate_existing=True
        )
        if record is None or record.chat_id != chat_id:
            raise TrainingConflictError("Unknown proposal")
        workflow = self._decode(record)
        if expected_revision is not None and workflow.revision != expected_revision:
            raise TrainingConflictError("Proposal revision changed")
        if workflow.state == "accepted":
            accepted_id = workflow.answers.get("accepted_plan_id")
            if accepted_id is None:
                raise TrainingConflictError("Accepted proposal has no plan")
            await self._session.commit()
            return int(accepted_id)
        session = await self._session.get(TrainingSessionRecord, chat_id, populate_existing=True)
        if session is not None and session.current_plan_id != workflow.base_plan_id:
            workflow.state = "stale"
            record.state = workflow.state
            record.payload = workflow.model_dump(mode="json")
            await self._session.commit()
            raise TrainingConflictError("Base plan is no longer current")
        if (
            workflow.state != "awaiting_confirmation"
            or workflow.draft is None
            or workflow.report is None
            or session is None
            or session.current_plan_id != workflow.base_plan_id
        ):
            raise TrainingConflictError("Proposal is not ready or its base plan changed")
        base = await self._session.get(TrainingPlanRecord, workflow.base_plan_id)
        if base is None:
            raise TrainingConflictError("Base plan disappeared")
        cycle_id = base.mesocycle_id
        if workflow.kind == "renewal":
            previous = await self._cycle_record(chat_id)
            if previous is None or previous.completed_at is None:
                raise TrainingConflictError("Previous mesocycle must be confirmed complete")
            cycle = TrainingMesocycleRecord(
                chat_id=chat_id,
                previous_cycle_id=previous.id,
                started_at=start,
                expected_end_at=expected_end(start),
                reminders_enabled=previous.reminders_enabled,
                message_thread_id=previous.message_thread_id,
            )
            self._session.add(cycle)
            await self._session.flush()
            cycle_id = cycle.id
        version = await self._session.scalar(
            select(func.max(TrainingPlanRecord.version)).where(
                TrainingPlanRecord.chat_id == chat_id
            )
        )
        trace = workflow.prompt_trace or {}
        plan = TrainingPlanRecord(
            chat_id=chat_id,
            version=(version or 0) + 1,
            mesocycle_id=cycle_id,
            parent_plan_id=base.id,
            change_kind=workflow.kind,
            plan=workflow.draft.model_dump(mode="json"),
            report=workflow.report,
            model=trace.get("model"),
            skill_name=trace.get("skill_name"),
            prompt_hash=trace.get("prompt_hash"),
            skill_hash=trace.get("skill_hash"),
            retrieved_exercise_ids=trace.get("retrieved_exercise_ids"),
        )
        self._session.add(plan)
        await self._session.flush()
        session.current_plan_id = plan.id
        session.updated_at = start
        workflow.state = "accepted"
        workflow.answers["accepted_plan_id"] = str(plan.id)
        record.state = workflow.state
        record.payload = workflow.model_dump(mode="json")
        await self._session.commit()
        return plan.id

    async def cancel(self, chat_id: int) -> None:
        workflow = await self.get_workflow(chat_id)
        if workflow:
            workflow.state = "cancelled"
            await self.save(chat_id, workflow)

    async def _check_current_plan(self, chat_id: int, expected_plan_id: int | None) -> None:
        if expected_plan_id is not None:
            session = await self._session.get(
                TrainingSessionRecord, chat_id, populate_existing=True
            )
            if session is None or session.current_plan_id != expected_plan_id:
                raise TrainingConflictError("Callback base plan is no longer current")

    async def close_cycle(
        self, chat_id: int, now: datetime, expected_plan_id: int | None = None
    ) -> None:
        await self._lock(chat_id)
        await self._check_current_plan(chat_id, expected_plan_id)
        cycle = await self._cycle_record(chat_id)
        if cycle is None:
            raise TrainingConflictError("No current mesocycle")
        cycle.completed_at = cycle.completed_at or now
        await self._session.commit()

    async def set_start(self, chat_id: int, start: datetime) -> None:
        await self._lock(chat_id)
        cycle = await self._cycle_record(chat_id)
        if cycle is None or cycle.started_at is not None:
            raise TrainingConflictError("Only an undated legacy cycle can receive a start")
        cycle.started_at = start
        cycle.expected_end_at = expected_end(start)
        await self._session.commit()

    async def set_reminders(self, chat_id: int, enabled: bool) -> None:
        await self._lock(chat_id)
        cycle = await self._cycle_record(chat_id)
        if cycle is None:
            raise TrainingConflictError("No current mesocycle")
        cycle.reminders_enabled = enabled
        await self._session.commit()

    async def postpone(
        self, chat_id: int, until: datetime, expected_plan_id: int | None = None
    ) -> None:
        await self._lock(chat_id)
        await self._check_current_plan(chat_id, expected_plan_id)
        cycle = await self._cycle_record(chat_id)
        if cycle is None:
            raise TrainingConflictError("No current mesocycle")
        if cycle.completed_at:
            raise TrainingConflictError("A closed mesocycle cannot be postponed")
        cycle.expected_end_at = until
        await self._session.execute(
            insert(TrainingNotificationRecord)
            .values(mesocycle_id=cycle.id, occasion=0, due_at=until, state="cancelled")
            .on_conflict_do_nothing()
        )
        await self._session.execute(
            update(TrainingNotificationRecord)
            .where(
                TrainingNotificationRecord.mesocycle_id == cycle.id,
                TrainingNotificationRecord.state.in_(("pending", "sending")),
            )
            .values(state="cancelled", lease_until=None)
        )
        occasion = await self._session.scalar(
            select(func.max(TrainingNotificationRecord.occasion)).where(
                TrainingNotificationRecord.mesocycle_id == cycle.id
            )
        )
        self._session.add(
            TrainingNotificationRecord(
                mesocycle_id=cycle.id,
                occasion=(occasion if occasion is not None else 0) + 1,
                due_at=until,
            )
        )
        await self._session.commit()

    async def effective_profile(self, chat_id: int) -> InterviewerProfile | None:
        records = await self._session.scalars(
            select(TrainingWorkflowRecord)
            .where(
                TrainingWorkflowRecord.chat_id == chat_id,
                TrainingWorkflowRecord.state == "accepted",
            )
            .order_by(TrainingWorkflowRecord.id.desc())
        )
        for record in records:
            profile = self._decode(record).effective_profile
            if profile is not None:
                return profile
        return None

    async def remember_thread(self, chat_id: int, thread_id: int | None) -> None:
        await self._lock(chat_id)
        cycle = await self._cycle_record(chat_id)
        if cycle and cycle.message_thread_id != thread_id:
            cycle.message_thread_id = thread_id
        await self._session.commit()

    async def enqueue_due(self, now: datetime) -> None:
        statement = (
            select(TrainingMesocycleRecord)
            .join(TrainingPlanRecord, TrainingPlanRecord.mesocycle_id == TrainingMesocycleRecord.id)
            .join(
                TrainingSessionRecord,
                TrainingSessionRecord.current_plan_id == TrainingPlanRecord.id,
            )
            .where(
                TrainingMesocycleRecord.expected_end_at <= now,
                TrainingMesocycleRecord.reminders_enabled.is_(True),
                TrainingMesocycleRecord.completed_at.is_(None),
            )
        )
        for cycle in (await self._session.scalars(statement)).all():
            await self._session.execute(
                insert(TrainingNotificationRecord)
                .values(mesocycle_id=cycle.id, occasion=0, due_at=now)
                .on_conflict_do_nothing()
            )
        await self._session.commit()

    async def claim_reminder(self, now: datetime) -> ReminderDelivery | None:
        record = await self._session.scalar(
            select(TrainingNotificationRecord)
            .where(
                TrainingNotificationRecord.state.in_(("pending", "sending")),
                TrainingNotificationRecord.due_at <= now,
                (TrainingNotificationRecord.lease_until.is_(None))
                | (TrainingNotificationRecord.lease_until <= now),
            )
            .order_by(TrainingNotificationRecord.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            await self._session.commit()
            return None
        cycle = await self._session.get(TrainingMesocycleRecord, record.mesocycle_id)
        if cycle is None:
            raise TrainingConflictError("Notification cycle disappeared")
        current = await self._cycle_record(cycle.chat_id)
        workflow = await self.get_workflow(cycle.chat_id)
        if (
            current is None
            or current.id != cycle.id
            or not cycle.reminders_enabled
            or cycle.completed_at is not None
            or cycle.expected_end_at is None
            or cycle.expected_end_at > now
            or workflow is not None
        ):
            record.state = "cancelled"
            await self._session.commit()
            return None
        record.state = "sending"
        record.lease_until = now + timedelta(minutes=2)
        record.attempts += 1
        delivery = ReminderDelivery(
            record.id, cycle.chat_id, cycle.message_thread_id, record.attempts
        )
        await self._session.commit()
        return delivery

    async def reserve_interaction_reminder(
        self, chat_id: int, thread_id: int | None, now: datetime
    ) -> ReminderDelivery | None:
        await self._lock(chat_id)
        cycle = await self._cycle_record(chat_id)
        if (
            cycle is None
            or cycle.expected_end_at is None
            or cycle.expected_end_at > now
            or cycle.completed_at
            or not cycle.reminders_enabled
            or await self.get_workflow(chat_id) is not None
        ):
            await self._session.commit()
            return None
        cycle.message_thread_id = thread_id
        await self._session.execute(
            insert(TrainingNotificationRecord)
            .values(mesocycle_id=cycle.id, occasion=0, due_at=now)
            .on_conflict_do_nothing()
        )
        record = await self._session.scalar(
            select(TrainingNotificationRecord)
            .where(
                TrainingNotificationRecord.mesocycle_id == cycle.id,
                TrainingNotificationRecord.state.in_(("pending", "sending")),
                TrainingNotificationRecord.due_at <= now,
                TrainingNotificationRecord.lease_until.is_(None)
                | (TrainingNotificationRecord.lease_until <= now),
            )
            .with_for_update(skip_locked=True)
            .order_by(TrainingNotificationRecord.id)
            .limit(1)
        )
        if record is None:
            await self._session.commit()
            return None
        record.state = "sending"
        record.lease_until = now + timedelta(minutes=2)
        record.attempts += 1
        delivery = ReminderDelivery(record.id, chat_id, thread_id, record.attempts)
        await self._session.commit()
        return delivery

    async def finish_reminder(
        self, delivery: ReminderDelivery, retry_at: datetime | None = None, failed: bool = False
    ) -> None:
        record = await self._session.scalar(
            select(TrainingNotificationRecord)
            .where(TrainingNotificationRecord.id == delivery.id)
            .with_for_update()
        )
        if record is None:
            raise TrainingConflictError("Notification disappeared")
        if record.attempts != delivery.attempts or record.state != "sending":
            raise TrainingConflictError("Notification lease no longer owned")
        record.state = "failed" if failed else ("pending" if retry_at else "sent")
        record.lease_until = None
        if retry_at:
            record.due_at = retry_at
        await self._session.commit()
