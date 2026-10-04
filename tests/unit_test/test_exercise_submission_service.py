from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from fitcoach.domain.exercise import Exercise, ExerciseMatch
from fitcoach.domain.exercise_submission import (
    ExerciseCuratorTurn,
    ExerciseProposal,
    ExerciseSubmission,
    ExerciseSubmissionStatus,
)
from fitcoach.service.agent.exercise_curator_chain import ExerciseCuratorReply
from fitcoach.service.exercise_submission_service import ExerciseSubmissionService


def proposal() -> ExerciseProposal:
    return ExerciseProposal(
        name="backpack row",
        category="back",
        body_part="back",
        equipment="body weight",
        target="lats",
        secondary_muscles=["biceps"],
        instructions_en="Hold the backpack securely, hinge forward, and row toward the torso.",
    )


def submission(
    exercise: ExerciseProposal | None = None,
    status: ExerciseSubmissionStatus = ExerciseSubmissionStatus.DRAFT,
    raw_description: str = "remo con mochila",
) -> ExerciseSubmission:
    now = datetime.now(UTC)
    return ExerciseSubmission(
        id=12,
        chat_id=7,
        message_thread_id=None,
        raw_description=raw_description,
        proposal=exercise,
        status=status,
        model="curator",
        created_at=now,
        updated_at=now,
    )


def service() -> tuple[ExerciseSubmissionService, AsyncMock, AsyncMock, AsyncMock]:
    curator = AsyncMock()
    repository = AsyncMock()
    duplicate_detector = AsyncMock()
    return (
        ExerciseSubmissionService(curator, repository, duplicate_detector, "curator"),
        curator,
        repository,
        duplicate_detector,
    )


@pytest.mark.asyncio
async def test_empty_command_starts_persisted_guided_draft_without_calling_model() -> None:
    subject, curator, repository, _ = service()
    repository.get_draft.return_value = None

    reply = await subject.handle(7, None, "/add_exercise", command=True)

    repository.create.assert_awaited_once_with(7, None, "", None, "curator")
    curator.propose.assert_not_awaited()
    assert "Describe el ejercicio" in reply.messages[0]


@pytest.mark.asyncio
async def test_generated_proposal_is_saved_and_previewed_with_duplicate_warning() -> None:
    subject, curator, repository, duplicate_detector = service()
    repository.get_draft.return_value = None
    repository.create.return_value = submission(proposal())
    curator.propose.return_value = ExerciseCuratorReply(
        ExerciseCuratorTurn(
            status="proposal", reply="He preparado la propuesta.", proposal=proposal()
        ),
        [],
    )
    duplicate_detector.find.return_value = ExerciseMatch(
        Exercise(id=99, name="backpack bent-over row"), 0.04
    )

    reply = await subject.handle(
        7, None, "Quiero añadir un ejercicio: remo con mochila", command=False
    )

    assert len(reply.messages) == 3
    assert "PROPUESTA #12" in reply.messages[1]
    assert "Posible duplicado del ejercicio #99" in reply.messages[1]
    assert reply.invoked_model is True
    repository.create.assert_awaited_once()
    assert repository.create.await_args.args[-1] == 99


@pytest.mark.asyncio
async def test_clarification_keeps_an_incomplete_draft() -> None:
    subject, curator, repository, duplicate_detector = service()
    repository.get_draft.return_value = None
    repository.create.return_value = submission(None)
    curator.propose.return_value = ExerciseCuratorReply(
        ExerciseCuratorTurn(
            status="clarification",
            reply="¿Qué material utilizas?",
            proposal=None,
        ),
        [],
    )

    reply = await subject.handle(7, None, "/add_exercise remo", command=True)

    assert reply.messages == ["¿Qué material utilizas?"]
    duplicate_detector.find.assert_not_awaited()
    assert repository.create.await_args.args[3] is None


@pytest.mark.asyncio
async def test_clarification_answer_updates_existing_draft_context() -> None:
    subject, curator, repository, duplicate_detector = service()
    repository.get_draft.return_value = submission(None)
    repository.update_draft.return_value = submission(proposal())
    curator.propose.return_value = ExerciseCuratorReply(
        ExerciseCuratorTurn(status="proposal", reply="Preparado.", proposal=proposal()), []
    )
    duplicate_detector.find.return_value = None

    await subject.handle(7, None, "una mochila cargada", command=False)

    description = curator.propose.await_args.args[0]
    assert description == "remo con mochila\nUser clarification: una mochila cargada"
    repository.update_draft.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirmation_submits_complete_draft_without_invoking_model() -> None:
    subject, curator, repository, _ = service()
    repository.get_draft.return_value = submission(proposal())
    repository.set_status.return_value = submission(
        proposal(), ExerciseSubmissionStatus.PENDING
    )

    reply = await subject.handle(7, None, "confirmar", command=False)

    repository.set_status.assert_awaited_once_with(
        12,
        ExerciseSubmissionStatus.DRAFT,
        ExerciseSubmissionStatus.PENDING,
    )
    curator.propose.assert_not_awaited()
    assert "moderación" in reply.messages[0]


@pytest.mark.asyncio
async def test_natural_intent_requires_explicit_addition_language() -> None:
    subject, _, _, _ = service()

    assert subject.is_natural_intent("Quiero añadir un ejercicio de espalda")
    assert not subject.is_natural_intent("Me gusta el remo con mancuerna")


@pytest.mark.asyncio
async def test_model_requirement_excludes_start_confirmation_and_cancellation() -> None:
    subject, _, repository, _ = service()
    repository.get_draft.side_effect = [None, submission(proposal()), submission(proposal())]

    assert not await subject.will_invoke_model(7, "/add_exercise", command=True)
    assert not await subject.will_invoke_model(7, "confirmar", command=False)
    assert not await subject.will_invoke_model(7, "cancelar", command=False)
