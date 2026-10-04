"""PostgreSQL persistence for user-proposed exercises."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.domain.exercise_submission import (
    ExerciseProposal,
    ExerciseSubmission,
    ExerciseSubmissionStatus,
)
from fitcoach.infrastructure.database.models import ExerciseSubmissionRecord


class ExerciseSubmissionConflictError(RuntimeError):
    """The submission no longer exists in the expected lifecycle state."""


class PostgresExerciseSubmissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        chat_id: int,
        message_thread_id: int | None,
        raw_description: str,
        proposal: ExerciseProposal | None,
        model: str,
        duplicate_exercise_id: int | None = None,
    ) -> ExerciseSubmission:
        current = await self.get_draft(chat_id)
        if current is not None:
            raise ExerciseSubmissionConflictError("The user already has an exercise draft")
        record = ExerciseSubmissionRecord(
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            raw_description=raw_description,
            proposal=proposal.model_dump(mode="json") if proposal is not None else None,
            status=ExerciseSubmissionStatus.DRAFT.value,
            model=model,
            duplicate_exercise_id=duplicate_exercise_id,
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return self._to_domain(record)

    async def get(self, submission_id: int) -> ExerciseSubmission | None:
        record = await self._session.get(
            ExerciseSubmissionRecord, submission_id, populate_existing=True
        )
        return self._to_domain(record) if record else None

    async def get_draft(self, chat_id: int) -> ExerciseSubmission | None:
        record = await self._session.scalar(
            select(ExerciseSubmissionRecord)
            .where(
                ExerciseSubmissionRecord.chat_id == chat_id,
                ExerciseSubmissionRecord.status == ExerciseSubmissionStatus.DRAFT.value,
            )
            .execution_options(populate_existing=True)
        )
        return self._to_domain(record) if record else None

    async def list_pending(self, limit: int = 20) -> list[ExerciseSubmission]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        records = await self._session.scalars(
            select(ExerciseSubmissionRecord)
            .where(ExerciseSubmissionRecord.status == ExerciseSubmissionStatus.PENDING.value)
            .order_by(ExerciseSubmissionRecord.id)
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return [self._to_domain(record) for record in records]

    async def update_draft(
        self,
        chat_id: int,
        raw_description: str,
        proposal: ExerciseProposal | None,
        duplicate_exercise_id: int | None = None,
    ) -> ExerciseSubmission:
        record = await self._session.scalar(
            select(ExerciseSubmissionRecord)
            .where(
                ExerciseSubmissionRecord.chat_id == chat_id,
                ExerciseSubmissionRecord.status == ExerciseSubmissionStatus.DRAFT.value,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if record is None:
            await self._session.rollback()
            raise ExerciseSubmissionConflictError("The user has no exercise draft")
        record.raw_description = raw_description
        record.proposal = proposal.model_dump(mode="json") if proposal is not None else None
        record.duplicate_exercise_id = duplicate_exercise_id
        record.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(record)
        return self._to_domain(record)

    async def set_status(
        self,
        submission_id: int,
        expected: ExerciseSubmissionStatus,
        status: ExerciseSubmissionStatus,
        *,
        reviewed_by: int | None = None,
        moderation_notes: str | None = None,
        published_exercise_id: int | None = None,
    ) -> ExerciseSubmission:
        record = await self._session.scalar(
            select(ExerciseSubmissionRecord)
            .where(ExerciseSubmissionRecord.id == submission_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if record is None or record.status != expected.value:
            await self._session.rollback()
            raise ExerciseSubmissionConflictError("Submission state changed")
        record.status = status.value
        record.updated_at = datetime.now(UTC)
        record.reviewed_by = reviewed_by
        record.moderation_notes = moderation_notes
        record.published_exercise_id = published_exercise_id
        if status in {ExerciseSubmissionStatus.APPROVED, ExerciseSubmissionStatus.REJECTED}:
            record.reviewed_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(record)
        return self._to_domain(record)

    @staticmethod
    def _to_domain(record: ExerciseSubmissionRecord) -> ExerciseSubmission:
        return ExerciseSubmission(
            id=record.id,
            chat_id=record.chat_id,
            message_thread_id=record.message_thread_id,
            raw_description=record.raw_description,
            proposal=(
                ExerciseProposal.model_validate(record.proposal)
                if record.proposal is not None
                else None
            ),
            status=ExerciseSubmissionStatus(record.status),
            model=record.model,
            duplicate_exercise_id=record.duplicate_exercise_id,
            moderation_notes=record.moderation_notes,
            reviewed_by=record.reviewed_by,
            published_exercise_id=record.published_exercise_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            reviewed_at=record.reviewed_at,
        )
