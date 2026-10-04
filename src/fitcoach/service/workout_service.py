"""Journal operations and descriptive progress, never modifying prescriptions."""

from fitcoach.domain.training_lifecycle import utc_now
from fitcoach.domain.workout import (
    MAX_EXERCISES,
    MAX_HISTORY,
    ExerciseHistory,
    ExerciseProgress,
    StartWorkout,
    UpdateWorkout,
    WorkoutBootstrap,
    WorkoutNotFoundError,
    WorkoutProgress,
    WorkoutSession,
    WorkoutSet,
)
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.infrastructure.database.postgres_workout_repository import PostgresWorkoutRepository
from fitcoach.repository.conversation_repository import ConversationRepository
from fitcoach.service.training_view import current_week


class WorkoutService:
    def __init__(
        self,
        workouts: PostgresWorkoutRepository,
        conversation: ConversationRepository,
        training: PostgresTrainingRepository,
    ) -> None:
        self._workouts = workouts
        self._conversation = conversation
        self._training = training

    async def bootstrap(self, chat_id: int) -> WorkoutBootstrap:
        stored = await self._conversation.get_current_plan(chat_id)
        if stored is None:
            raise WorkoutNotFoundError("No current training plan")
        cycle = await self._training.get_cycle(chat_id)
        week, status = current_week(cycle, utc_now())
        return WorkoutBootstrap(
            plan_id=stored.id,
            version=stored.version,
            plan=stored.plan,
            cycle=cycle,
            current_week=week,
            calendar_status=status,
        )

    async def list_sessions(self, chat_id: int) -> list[WorkoutSession]:
        return await self._workouts.list_sessions(chat_id)

    async def get(self, chat_id: int, session_id: int) -> WorkoutSession:
        return await self._workouts.get(chat_id, session_id)

    async def start(self, chat_id: int, request: StartWorkout) -> WorkoutSession:
        return await self._workouts.start(chat_id, request)

    async def update(self, chat_id: int, session_id: int, patch: UpdateWorkout) -> WorkoutSession:
        return await self._workouts.update(chat_id, session_id, patch)

    async def progress(self, chat_id: int) -> WorkoutProgress:
        """Bounded chronological measured histories grouped by catalogue ID.

        Time-based sets have separate duration totals and are excluded from load comparisons. Weight
        zero is recorded zero load, not unknown; no load is inferred for None.
        Mixed rep prescriptions are descriptive totals, not strength estimates.
        """
        sessions = await self._workouts.list_sessions(chat_id, completed_only=True)
        grouped: dict[int, ExerciseProgress] = {}
        exercise_history_truncated = False
        # Latest recorded name wins deterministically, even if a catalogue label changed.
        for session in sessions:
            for actual in session.exercises:
                if actual.skipped or not any(item.completed for item in actual.sets):
                    continue
                planned = session.prescription.exercises[actual.position]
                if planned.exercise_id not in grouped:
                    if len(grouped) >= MAX_EXERCISES:
                        exercise_history_truncated = True
                        continue
                    grouped[planned.exercise_id] = ExerciseProgress(
                        exercise_id=planned.exercise_id, name=planned.name[:200], history=[]
                    )
        for session in sorted(
            sessions, key=lambda item: (item.completed_at or item.started_at, item.id)
        ):
            measurements: dict[int, list[WorkoutSet]] = {}
            for actual in session.exercises:
                if actual.skipped:
                    continue
                exercise_id = session.prescription.exercises[actual.position].exercise_id
                if exercise_id not in grouped:
                    continue
                measurements.setdefault(exercise_id, []).extend(
                    item for item in actual.sets if item.completed
                )
            for exercise_id, sets in measurements.items():
                if not sets:
                    continue
                repetitions = [item.reps for item in sets if item.reps is not None]
                durations = [
                    item.duration_seconds for item in sets if item.duration_seconds is not None
                ]
                weights = [
                    item.weight_kg
                    for item in sets
                    if item.reps is not None and item.weight_kg is not None
                ]
                rpes = [item.rpe for item in sets if item.rpe is not None]
                grouped[exercise_id].history.append(
                    ExerciseHistory(
                        date=(session.completed_at or session.started_at).isoformat(),
                        session_id=session.id,
                        total_reps=sum(repetitions) if repetitions else None,
                        total_duration_seconds=sum(durations) if durations else None,
                        total_sets=len(sets),
                        max_weight_kg=max(weights) if weights else None,
                        average_rpe=sum(rpes) / len(rpes) if rpes else None,
                    )
                )
        completed_count = await self._workouts.completed_count(chat_id)
        return WorkoutProgress(
            completed_sessions=completed_count,
            exercises=[grouped[key] for key in sorted(grouped) if grouped[key].history],
            history_limit=MAX_HISTORY,
            history_truncated=completed_count > len(sessions) or exercise_history_truncated,
        )
