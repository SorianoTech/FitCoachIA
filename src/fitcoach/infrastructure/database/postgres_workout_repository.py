import json
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.domain.trainer_plan import TrainingDay, TrainingPlan
from fitcoach.domain.training_lifecycle import utc_now
from fitcoach.domain.workout import (
    MAX_EXERCISES,
    MAX_HISTORY,
    StartWorkout,
    UpdateWorkout,
    WorkoutConflictError,
    WorkoutExercise,
    WorkoutNotFoundError,
    WorkoutSession,
    WorkoutSet,
    WorkoutValidationError,
)
from fitcoach.infrastructure.database.models import (
    TrainingPlanRecord,
    TrainingSessionRecord,
    WorkoutRequestRecord,
    WorkoutSessionRecord,
)

logger = logging.getLogger(__name__)


class PostgresWorkoutRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _decode(record: WorkoutSessionRecord) -> WorkoutSession:
        return WorkoutSession.model_validate_json(
            json.dumps({
                "id": record.id,
                "plan_id": record.plan_id,
                "mesocycle_id": record.mesocycle_id,
                "week": record.week,
                "day": record.day,
                "revision": record.revision,
                "status": record.status,
                "started_at": record.started_at.isoformat(),
                "completed_at": record.completed_at.isoformat() if record.completed_at else None,
                "prescription": record.prescription,
                "exercises": record.exercises,
            })
        )

    async def get(self, chat_id: int, session_id: int) -> WorkoutSession:
        record = await self._session.scalar(
            select(WorkoutSessionRecord).where(
                WorkoutSessionRecord.chat_id == chat_id, WorkoutSessionRecord.id == session_id
            )
        )
        if record is None:
            raise WorkoutNotFoundError("Workout not found")
        return self._decode(record)

    async def list_sessions(
        self, chat_id: int, *, completed_only: bool = False, mesocycle_id: int | None = None
    ) -> list[WorkoutSession]:
        statement = select(WorkoutSessionRecord).where(WorkoutSessionRecord.chat_id == chat_id)
        if completed_only:
            statement = statement.where(WorkoutSessionRecord.status == "completed")
        if mesocycle_id is not None:
            statement = statement.where(WorkoutSessionRecord.mesocycle_id == mesocycle_id)
        records = await self._session.scalars(
            statement.order_by(WorkoutSessionRecord.id.desc()).limit(MAX_HISTORY)
        )
        return [self._decode(record) for record in records]

    async def completed_count(self, chat_id: int) -> int:
        count = await self._session.scalar(
            select(func.count(WorkoutSessionRecord.id)).where(
                WorkoutSessionRecord.chat_id == chat_id,
                WorkoutSessionRecord.status == "completed",
            )
        )
        return count or 0

    async def start(self, chat_id: int, request: StartWorkout) -> WorkoutSession:
        # Same lock as plan activation/reset: snapshot and current-plan check are atomic.
        await self._session.execute(select(func.pg_advisory_xact_lock(chat_id)))
        previous = await self._session.get(
            WorkoutRequestRecord, (chat_id, str(request.request_id)), populate_existing=True
        )
        if previous:
            result = await self.get(chat_id, previous.session_id)
            if (previous.plan_id, result.week, result.day) != (
                request.plan_id,
                request.week,
                request.day,
            ):
                self._conflict(chat_id, "Request UUID already used with another payload")
            await self._session.commit()
            return result
        plan_record = await self._session.scalar(
            select(TrainingPlanRecord).where(
                TrainingPlanRecord.id == request.plan_id, TrainingPlanRecord.chat_id == chat_id
            )
        )
        if plan_record is None:
            raise WorkoutNotFoundError("Training plan not found")
        active = await self._session.get(TrainingSessionRecord, chat_id, populate_existing=True)
        if active is None or active.current_plan_id != request.plan_id:
            self._conflict(chat_id, "Training plan is no longer current")
        slot = select(WorkoutSessionRecord).where(
            WorkoutSessionRecord.chat_id == chat_id,
            WorkoutSessionRecord.week == request.week,
            WorkoutSessionRecord.day == request.day,
        )
        if plan_record.mesocycle_id is None:
            slot = slot.where(
                WorkoutSessionRecord.mesocycle_id.is_(None),
                WorkoutSessionRecord.plan_id == request.plan_id,
            )
        else:
            slot = slot.where(WorkoutSessionRecord.mesocycle_id == plan_record.mesocycle_id)
        record = await self._session.scalar(slot)
        if record is None:
            plan = TrainingPlan.model_validate_json(json.dumps(plan_record.plan))
            prescription = next(
                (
                    day
                    for week in plan.weeks
                    if week.week == request.week
                    for day in week.days
                    if day.day == request.day
                ),
                None,
            )
            if prescription is None:
                raise WorkoutValidationError("Day is not present in the training plan")
            if len(prescription.exercises) > MAX_EXERCISES:
                raise WorkoutValidationError("Prescription exceeds journal exercise limit")
            actual = [
                WorkoutExercise(
                    position=position,
                    skipped=False,
                    sets=[
                        WorkoutSet(number=number, completed=False)
                        for number in range(1, exercise.sets + 1)
                    ],
                ).model_dump(mode="json")
                for position, exercise in enumerate(prescription.exercises)
            ]
            record = WorkoutSessionRecord(
                chat_id=chat_id,
                request_id=str(request.request_id),
                plan_id=plan_record.id,
                mesocycle_id=plan_record.mesocycle_id,
                week=request.week,
                day=request.day,
                revision=0,
                status="in_progress",
                started_at=utc_now(),
                prescription=prescription.model_dump(mode="json"),
                exercises=actual,
            )
            self._session.add(record)
            await self._session.flush()
        self._session.add(
            WorkoutRequestRecord(
                chat_id=chat_id,
                request_id=str(request.request_id),
                session_id=record.id,
                plan_id=request.plan_id,
            )
        )
        result = self._decode(record)
        await self._session.commit()
        return result

    @staticmethod
    def _conflict(chat_id: int, message: str) -> None:
        logger.warning("Workout conflict chat_id=%s: %s", chat_id, message)
        raise WorkoutConflictError(message)

    async def update(self, chat_id: int, session_id: int, patch: UpdateWorkout) -> WorkoutSession:
        # Lock ordering matches reset/start, then serializes revisions on this row.
        await self._session.execute(select(func.pg_advisory_xact_lock(chat_id)))
        record = await self._session.scalar(
            select(WorkoutSessionRecord)
            .where(WorkoutSessionRecord.id == session_id, WorkoutSessionRecord.chat_id == chat_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if record is None:
            raise WorkoutNotFoundError("Workout not found")
        if record.revision != patch.revision:
            self._conflict(chat_id, "Workout revision changed")
        if record.status == "completed":
            self._conflict(chat_id, "Completed workouts are read-only")
        prescription = TrainingDay.model_validate_json(json.dumps(record.prescription))
        patch.validate_prescription(prescription)
        record.exercises = [
            item.model_dump(mode="json")
            for item in sorted(patch.exercises, key=lambda x: x.position)
        ]
        record.status = patch.status
        record.revision += 1
        if patch.status == "completed":
            record.completed_at = utc_now()
        result = self._decode(record)
        await self._session.commit()
        return result

    async def performance_summary(self, chat_id: int, mesocycle_id: int) -> dict[str, object]:
        """At most 28 slots and 100 performed exercise entries; never prescribe results.

        Zero weight is an explicit measurement; None means unknown. Timed and
        repetition measurements stay separate instead of inventing volume.
        """
        sessions = await self.list_sessions(chat_id, completed_only=True, mesocycle_id=mesocycle_id)
        slots: list[dict[str, object]] = []
        measurements: list[dict[str, object]] = []
        truncated = False
        recorded_sets = 0
        repetition_sets = 0
        duration_sets = 0
        unknown_weight_sets = 0
        unknown_rpe_sets = 0
        skipped_exercises = 0
        prescribed_sets = 0
        for session in sessions:
            prescribed_sets += sum(item.sets for item in session.prescription.exercises)
            for actual in session.exercises:
                if actual.skipped:
                    skipped_exercises += 1
                    continue
                for item in actual.sets:
                    if not item.completed:
                        continue
                    recorded_sets += 1
                    repetition_sets += int(item.reps is not None)
                    duration_sets += int(item.duration_seconds is not None)
                    unknown_weight_sets += int(item.weight_kg is None)
                    unknown_rpe_sets += int(item.rpe is None)
        for session in reversed(sessions[:28]):
            slots.append({
                "session_id": session.id,
                "week": session.week,
                "day": session.day,
                "date": session.completed_at.isoformat() if session.completed_at else None,
            })
            for actual in session.exercises:
                sets = [item.model_dump(mode="json") for item in actual.sets if item.completed]
                if not sets or actual.skipped:
                    continue
                if len(measurements) >= MAX_EXERCISES:
                    truncated = True
                    continue
                planned = session.prescription.exercises[actual.position]
                measurements.append({
                    "session_id": session.id,
                    "exercise_id": planned.exercise_id,
                    "position": actual.position,
                    "sets": sets,
                })
        return {
            "mesocycle_id": mesocycle_id,
            "completed_sessions": len(sessions),
            "completed_slots": slots,
            "measurements": measurements,
            "recorded_sets": recorded_sets,
            "repetition_sets": repetition_sets,
            "duration_sets": duration_sets,
            "skipped_exercises": skipped_exercises,
            "coverage": {
                "prescribed_sets_in_completed_sessions": prescribed_sets,
                "unknown_weight_sets": unknown_weight_sets,
                "unknown_rpe_sets": unknown_rpe_sets,
                "unrecorded_training": "unknown; absence of logs is not evidence of no training",
                "history_limit": MAX_HISTORY,
            },
            "units": {"reps": "repetitions", "duration_seconds": "seconds", "weight_kg": "kg"},
            "truncated": truncated or len(sessions) > 28,
        }
