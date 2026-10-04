"""Administrator review and publication of submitted exercises."""

from dataclasses import dataclass

from fitcoach.domain.constants import Constants
from fitcoach.domain.exercise_submission import (
    ExerciseSubmission,
    ExerciseSubmissionStatus,
    build_exercise_metadata_text,
)
from fitcoach.infrastructure.ia.embedder_client import Embedder
from fitcoach.repository.exercise_publisher import ExercisePublisher
from fitcoach.repository.exercise_submission_repository import ExerciseSubmissionRepository


@dataclass(frozen=True, slots=True)
class ExerciseModerationNotification:
    chat_id: int
    thread_id: int | None
    text: str


@dataclass(frozen=True, slots=True)
class ExerciseModerationReply:
    messages: list[str]
    notification: ExerciseModerationNotification | None = None


class ExerciseModerationService:
    def __init__(
        self,
        repository: ExerciseSubmissionRepository,
        embedder: Embedder,
        publisher: ExercisePublisher | None,
        admin_user_ids: set[int],
    ) -> None:
        self._repository = repository
        self._embedder = embedder
        self._publisher = publisher
        self._admin_user_ids = admin_user_ids

    async def handle(self, actor_user_id: int, text: str) -> ExerciseModerationReply:
        if actor_user_id not in self._admin_user_ids:
            return ExerciseModerationReply([Constants.EXERCISE_MODERATION_FORBIDDEN])
        command, _, arguments = text.partition(" ")
        if command == "/review_exercises":
            return await self._list_pending()
        if command == "/approve_exercise":
            return await self._approve(actor_user_id, arguments)
        if command == "/reject_exercise":
            return await self._reject(actor_user_id, arguments)
        return ExerciseModerationReply([Constants.EXERCISE_MODERATION_USAGE])

    async def _list_pending(self) -> ExerciseModerationReply:
        pending = await self._repository.list_pending()
        if not pending:
            return ExerciseModerationReply([Constants.EXERCISE_MODERATION_EMPTY])
        return ExerciseModerationReply([
            "\n\n".join(self._summary(submission) for submission in pending),
            Constants.EXERCISE_MODERATION_USAGE,
        ])

    async def _approve(self, actor_user_id: int, arguments: str) -> ExerciseModerationReply:
        submission_id = self._parse_id(arguments)
        if submission_id is None:
            return ExerciseModerationReply([Constants.EXERCISE_MODERATION_USAGE])
        if self._publisher is None:
            return ExerciseModerationReply([
                Constants.EXERCISE_MODERATION_PUBLISHER_UNAVAILABLE
            ])
        submission = await self._repository.get(submission_id)
        if (
            submission is None
            or submission.status != ExerciseSubmissionStatus.PENDING
            or submission.proposal is None
        ):
            return ExerciseModerationReply([Constants.EXERCISE_MODERATION_USAGE])
        proposal = submission.proposal
        vectors = await self._embedder.embed([
            build_exercise_metadata_text(proposal)
        ])
        exercise_id = await self._publisher.publish(
            submission.id, proposal, vectors[0]
        )
        approved = await self._repository.set_status(
            submission.id,
            ExerciseSubmissionStatus.PENDING,
            ExerciseSubmissionStatus.APPROVED,
            reviewed_by=actor_user_id,
            published_exercise_id=exercise_id,
        )
        return ExerciseModerationReply(
            [
                Constants.EXERCISE_MODERATION_APPROVED.format(
                    submission_id=approved.id, exercise_id=exercise_id
                )
            ],
            ExerciseModerationNotification(
                approved.chat_id,
                approved.message_thread_id,
                Constants.EXERCISE_SUBMISSION_APPROVED_USER.format(
                    name=proposal.name
                ),
            ),
        )

    async def _reject(self, actor_user_id: int, arguments: str) -> ExerciseModerationReply:
        raw_id, separator, reason = arguments.strip().partition(" ")
        submission_id = self._parse_id(raw_id)
        if submission_id is None or not separator or not reason.strip():
            return ExerciseModerationReply([Constants.EXERCISE_MODERATION_USAGE])
        submission = await self._repository.get(submission_id)
        if (
            submission is None
            or submission.status != ExerciseSubmissionStatus.PENDING
            or submission.proposal is None
        ):
            return ExerciseModerationReply([Constants.EXERCISE_MODERATION_USAGE])
        proposal = submission.proposal
        rejected = await self._repository.set_status(
            submission.id,
            ExerciseSubmissionStatus.PENDING,
            ExerciseSubmissionStatus.REJECTED,
            reviewed_by=actor_user_id,
            moderation_notes=reason.strip(),
        )
        return ExerciseModerationReply(
            [
                Constants.EXERCISE_MODERATION_REJECTED.format(
                    submission_id=rejected.id
                )
            ],
            ExerciseModerationNotification(
                rejected.chat_id,
                rejected.message_thread_id,
                Constants.EXERCISE_SUBMISSION_REJECTED_USER.format(
                    name=proposal.name,
                    reason=reason.strip(),
                ),
            ),
        )

    @staticmethod
    def _parse_id(value: str) -> int | None:
        try:
            parsed = int(value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _summary(submission: ExerciseSubmission) -> str:
        proposal = submission.proposal
        if proposal is None:
            return f"#{submission.id} · propuesta incompleta"
        duplicate = (
            f" · posible duplicado #{submission.duplicate_exercise_id}"
            if submission.duplicate_exercise_id is not None
            else ""
        )
        return (
            f"#{submission.id} · {proposal.name}\n"
            f"{proposal.target} · {proposal.equipment}{duplicate}\n"
            f"{proposal.instructions_en}\n"
            f"Calidad IA: {proposal.quality.validity} "
            f"({proposal.quality.confidence:.0%})\n"
            f"Motivo: {proposal.quality.rationale}"
        )
