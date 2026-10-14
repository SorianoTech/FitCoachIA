import json
from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.scheduled_job import ClaimedJob, JobOutcome, JobState, JobType
from fitcoach.domain.training_lifecycle import (
    Mesocycle,
    TrainingWorkflow,
    expected_end,
    utc_now,
)
from fitcoach.infrastructure.database.models import (
    JobExecutionRecord,
    TrainingMesocycleRecord,
    TrainingPlanRecord,
    TrainingSessionRecord,
    TrainingWorkflowRecord,
)
from fitcoach.infrastructure.database.postgres_job_repository import (
    PostgresJobRepository,
    cancel_pending_jobs,
    cycle_jobs,
    ensure_training_reminder,
    reschedule_training_reminder,
    schedule_cycle_jobs,
)
from fitcoach.repository.job_repository import JobConflictError
from fitcoach.repository.training_repository import (
    ReminderDelivery,
    ReminderTarget,
    TrainingConflictError,
)

_OPEN = ("reviewing", "generating", "awaiting_confirmation")
_INTERACTION_LOCK = timedelta(minutes=2)


class PostgresTrainingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _lock(self, chat_id: int) -> None:
        await self._session.execute(select(func.pg_advisory_xact_lock(chat_id)))

    async def _cycle_record(self, chat_id: int) -> TrainingMesocycleRecord | None:
        cycle: TrainingMesocycleRecord | None = await self._session.scalar(
            select(TrainingMesocycleRecord)
            .join(TrainingPlanRecord, TrainingPlanRecord.mesocycle_id == TrainingMesocycleRecord.id)
            .join(
                TrainingSessionRecord,
                TrainingSessionRecord.current_plan_id == TrainingPlanRecord.id,
            )
            .where(TrainingSessionRecord.chat_id == chat_id, TrainingPlanRecord.chat_id == chat_id)
            .execution_options(populate_existing=True)
        )
        return cycle

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
            await schedule_cycle_jobs(self._session, cycle, utc_now())
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
            goal=workflow.draft.goal,
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
        await cancel_pending_jobs(self._session, cycle_jobs(cycle.id))
        await self._session.commit()

    async def set_start(self, chat_id: int, start: datetime) -> None:
        await self._lock(chat_id)
        cycle = await self._cycle_record(chat_id)
        if cycle is None or cycle.started_at is not None:
            raise TrainingConflictError("Only an undated legacy cycle can receive a start")
        cycle.started_at = start
        cycle.expected_end_at = expected_end(start)
        await schedule_cycle_jobs(self._session, cycle, utc_now())
        await self._session.commit()

    async def set_reminders(self, chat_id: int, enabled: bool) -> None:
        await self._lock(chat_id)
        cycle = await self._cycle_record(chat_id)
        if cycle is None:
            raise TrainingConflictError("No current mesocycle")
        cycle.reminders_enabled = enabled
        if enabled:
            await ensure_training_reminder(self._session, cycle)
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
        await reschedule_training_reminder(self._session, cycle, until)
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

    async def reminder_target(
        self, chat_id: int, mesocycle_id: int, now: datetime
    ) -> ReminderTarget | None:
        cycle = await self._cycle_record(chat_id)
        if cycle is None or cycle.id != mesocycle_id or not self._reminder_due(cycle, now):
            return None
        if await self.get_workflow(chat_id) is not None:
            return None
        return ReminderTarget(thread_id=cycle.message_thread_id)

    @staticmethod
    def _reminder_due(cycle: TrainingMesocycleRecord, now: datetime) -> bool:
        return (
            cycle.reminders_enabled
            and cycle.completed_at is None
            and cycle.expected_end_at is not None
            and cycle.expected_end_at <= now
        )

    async def reserve_interaction_reminder(
        self, chat_id: int, thread_id: int | None, now: datetime
    ) -> ReminderDelivery | None:
        await self._lock(chat_id)
        cycle = await self._cycle_record(chat_id)
        if (
            cycle is None
            or not self._reminder_due(cycle, now)
            or await self.get_workflow(chat_id) is not None
        ):
            await self._session.commit()
            return None
        cycle.message_thread_id = thread_id
        record = await self._session.scalar(
            select(JobExecutionRecord)
            .where(
                JobExecutionRecord.job_type == JobType.TRAINING_REMINDER,
                cycle_jobs(cycle.id),
                JobExecutionRecord.state.in_((JobState.PENDING, JobState.RUNNING)),
                JobExecutionRecord.execution_date <= now,
                JobExecutionRecord.locked_until.is_(None)
                | (JobExecutionRecord.locked_until <= now),
            )
            .with_for_update(skip_locked=True)
            .order_by(JobExecutionRecord.execution_date)
            .limit(1)
        )
        if record is None:
            await self._session.commit()
            return None
        record.state = JobState.RUNNING
        record.locked_until = now + _INTERACTION_LOCK
        record.attempts += 1
        delivery = ReminderDelivery(record.id, chat_id, thread_id, record.attempts)
        await self._session.commit()
        return delivery

    async def finish_reminder(
        self, delivery: ReminderDelivery, retry_at: datetime | None = None, failed: bool = False
    ) -> None:
        if failed:
            outcome = JobOutcome.failed()
        else:
            outcome = JobOutcome.retry(retry_at) if retry_at else JobOutcome.done()
        job = ClaimedJob(
            id=delivery.id,
            job_type=JobType.TRAINING_REMINDER,
            chat_id=delivery.chat_id,
            payload={},
            attempts=delivery.attempts,
            execution_date=utc_now(),
        )
        try:
            await PostgresJobRepository(self._session).finish(job, outcome, utc_now())
        except JobConflictError as error:
            raise TrainingConflictError("Notification lease no longer owned") from error
