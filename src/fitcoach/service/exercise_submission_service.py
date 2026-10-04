"""Application workflow for creating moderated exercise proposals."""

import re
from dataclasses import dataclass

from fitcoach.domain.constants import Constants
from fitcoach.domain.exercise_submission import ExerciseProposal, ExerciseSubmissionStatus
from fitcoach.domain.token_usage import TokenUsage
from fitcoach.repository.exercise_submission_repository import ExerciseSubmissionRepository
from fitcoach.service.agent.exercise_curator_chain import ExerciseCuratorChain
from fitcoach.service.agent.exercise_duplicate_detector import ExerciseDuplicateDetector

_NATURAL_INTENT = re.compile(
    r"^\s*(?:quiero|quisiera|me gustaría|podemos|puedes)\s+"
    r"(?:añadir|agregar|registrar|crear)\s+(?:un\s+)?(?:nuevo\s+)?ejercicio\b",
    re.IGNORECASE,
)
_CONFIRM = frozenset({"confirmar", "confirmo", "sí, confirmar", "si, confirmar"})
_CANCEL = frozenset({"cancelar", "cancelo"})
_MAX_DESCRIPTION_CHARS = 4000


@dataclass(frozen=True, slots=True)
class ExerciseSubmissionReply:
    messages: list[str]
    token_usages: list[TokenUsage]
    invoked_model: bool = False


class ExerciseSubmissionService:
    def __init__(
        self,
        curator: ExerciseCuratorChain,
        repository: ExerciseSubmissionRepository,
        duplicate_detector: ExerciseDuplicateDetector,
        model_name: str,
    ) -> None:
        self._curator = curator
        self._repository = repository
        self._duplicate_detector = duplicate_detector
        self._model_name = model_name

    async def has_draft(self, chat_id: int) -> bool:
        return await self._repository.get_draft(chat_id) is not None

    @staticmethod
    def is_natural_intent(text: str) -> bool:
        return _NATURAL_INTENT.match(text) is not None

    async def will_invoke_model(self, chat_id: int, text: str, *, command: bool) -> bool:
        draft = await self._repository.get_draft(chat_id)
        content = text.partition(" ")[2].strip() if command else text.strip()
        if content.casefold() in _CONFIRM | _CANCEL:
            return False
        if command and not content and draft is None:
            return False
        return bool(self._description(draft.raw_description if draft else "", content))

    async def handle(
        self,
        chat_id: int,
        message_thread_id: int | None,
        text: str,
        *,
        command: bool,
    ) -> ExerciseSubmissionReply:
        draft = await self._repository.get_draft(chat_id)
        content = text.partition(" ")[2].strip() if command else text.strip()
        normalized = content.casefold()

        if draft is not None and normalized in _CANCEL:
            await self._repository.set_status(
                draft.id,
                ExerciseSubmissionStatus.DRAFT,
                ExerciseSubmissionStatus.CANCELLED,
            )
            return ExerciseSubmissionReply([Constants.EXERCISE_SUBMISSION_CANCELLED], [])

        if draft is None and normalized in _CONFIRM | _CANCEL:
            return ExerciseSubmissionReply([Constants.EXERCISE_SUBMISSION_START], [])

        if draft is not None and normalized in _CONFIRM:
            if draft.proposal is None:
                return ExerciseSubmissionReply([Constants.EXERCISE_SUBMISSION_INCOMPLETE], [])
            await self._repository.set_status(
                draft.id,
                ExerciseSubmissionStatus.DRAFT,
                ExerciseSubmissionStatus.PENDING,
            )
            return ExerciseSubmissionReply([Constants.EXERCISE_SUBMISSION_PENDING], [])

        if command and not content and draft is None:
            await self._repository.create(
                chat_id, message_thread_id, "", None, self._model_name
            )
            return ExerciseSubmissionReply([Constants.EXERCISE_SUBMISSION_START], [])

        description = self._description(draft.raw_description if draft else "", content)
        if not description:
            return ExerciseSubmissionReply([Constants.EXERCISE_SUBMISSION_START], [])

        reply = await self._curator.propose(description)
        if reply.turn.status == "rejected":
            if draft is not None:
                await self._repository.set_status(
                    draft.id,
                    ExerciseSubmissionStatus.DRAFT,
                    ExerciseSubmissionStatus.CANCELLED,
                )
            return ExerciseSubmissionReply([reply.turn.reply], reply.token_usages, True)

        proposal = reply.turn.proposal
        duplicate = await self._duplicate_detector.find(proposal) if proposal is not None else None
        duplicate_id = duplicate.exercise.id if duplicate is not None else None
        if draft is None:
            draft = await self._repository.create(
                chat_id,
                message_thread_id,
                description,
                proposal,
                self._model_name,
                duplicate_id,
            )
        else:
            draft = await self._repository.update_draft(
                chat_id, description, proposal, duplicate_id
            )

        if proposal is None:
            return ExerciseSubmissionReply([reply.turn.reply], reply.token_usages, True)

        preview = self._preview(draft.id, proposal)
        if duplicate is not None:
            preview += Constants.EXERCISE_SUBMISSION_DUPLICATE.format(
                id=duplicate.exercise.id,
                name=duplicate.exercise.name,
                similarity=duplicate.similarity,
            )
        return ExerciseSubmissionReply(
            [reply.turn.reply, preview, Constants.EXERCISE_SUBMISSION_CONFIRM],
            reply.token_usages,
            True,
        )

    @staticmethod
    def _description(previous: str, content: str) -> str:
        combined = "\nUser clarification: ".join(part for part in (previous, content) if part)
        if len(combined) > _MAX_DESCRIPTION_CHARS:
            raise ValueError("Exercise description is too long")
        return combined

    @staticmethod
    def _preview(submission_id: int, proposal: ExerciseProposal) -> str:
        secondary = ", ".join(proposal.secondary_muscles) or "ninguno"
        return (
            f"PROPUESTA #{submission_id}\n"
            f"Nombre: {proposal.name}\n"
            f"Objetivo: {proposal.target} ({proposal.muscle_group})\n"
            f"Material: {proposal.equipment}\n"
            f"Secundarios: {secondary}\n"
            f"Instrucciones: {proposal.instructions_en}\n"
            f"Calidad IA: {proposal.quality.validity} "
            f"({proposal.quality.confidence:.0%})\n"
            f"Motivo: {proposal.quality.rationale}"
        )
