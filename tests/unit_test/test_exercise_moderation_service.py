from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from fitcoach.domain.exercise_submission import (
    ExerciseProposal,
    ExerciseQualityAssessment,
    ExerciseSubmission,
    ExerciseSubmissionStatus,
)
from fitcoach.service.exercise_moderation_service import ExerciseModerationService


def proposal() -> ExerciseProposal:
    return ExerciseProposal(
        name="backpack row",
        category="back",
        body_part="back",
        equipment="body weight",
        target="lats",
        secondary_muscles=["biceps"],
        instructions_en="Hold the backpack securely, hinge forward, and row toward the torso.",
        quality=ExerciseQualityAssessment(
            validity="valid",
            confidence=0.91,
            rationale="It is a coherent loaded horizontal pulling movement.",
            safety_notes=["Secure the backpack before starting."],
        ),
    )


def submission(
    status: ExerciseSubmissionStatus = ExerciseSubmissionStatus.PENDING,
) -> ExerciseSubmission:
    now = datetime.now(UTC)
    return ExerciseSubmission(
        id=12,
        chat_id=77,
        message_thread_id=5,
        raw_description="remo con mochila",
        proposal=proposal(),
        status=status,
        model="curator",
        duplicate_exercise_id=4,
        created_at=now,
        updated_at=now,
    )


def service(
    publisher: AsyncMock | None = None,
) -> tuple[ExerciseModerationService, AsyncMock, AsyncMock, AsyncMock]:
    repository = AsyncMock()
    embedder = AsyncMock()
    actual_publisher = publisher or AsyncMock()
    return (
        ExerciseModerationService(repository, embedder, actual_publisher, {9}),
        repository,
        embedder,
        actual_publisher,
    )


@pytest.mark.asyncio
async def test_rejects_non_admin_without_querying_submissions() -> None:
    subject, repository, _, _ = service()

    reply = await subject.handle(8, "/review_exercises")

    assert "permisos" in reply.messages[0]
    repository.list_pending.assert_not_awaited()


@pytest.mark.asyncio
async def test_lists_pending_proposals_and_duplicate_hint() -> None:
    subject, repository, _, _ = service()
    repository.list_pending.return_value = [submission()]

    reply = await subject.handle(9, "/review_exercises")

    assert "#12 · backpack row" in reply.messages[0]
    assert "posible duplicado #4" in reply.messages[0]
    assert "Calidad IA: valid (91%)" in reply.messages[0]


@pytest.mark.asyncio
async def test_approval_embeds_publishes_transitions_and_notifies_user() -> None:
    subject, repository, embedder, publisher = service()
    pending = submission()
    approved = pending.model_copy(
        update={
            "status": ExerciseSubmissionStatus.APPROVED,
            "published_exercise_id": 5000,
        }
    )
    repository.get.return_value = pending
    repository.set_status.return_value = approved
    embedder.embed.return_value = [[0.1] * 384]
    publisher.publish.return_value = 5000

    reply = await subject.handle(9, "/approve_exercise 12")

    publisher.publish.assert_awaited_once_with(12, pending.proposal, [0.1] * 384)
    repository.set_status.assert_awaited_once_with(
        12,
        ExerciseSubmissionStatus.PENDING,
        ExerciseSubmissionStatus.APPROVED,
        reviewed_by=9,
        published_exercise_id=5000,
    )
    assert "ejercicio #5000" in reply.messages[0]
    assert reply.notification is not None
    assert reply.notification.chat_id == 77
    assert "ya forma parte del catálogo" in reply.notification.text


@pytest.mark.asyncio
async def test_rejection_requires_reason_and_notifies_user() -> None:
    subject, repository, _, _ = service()
    pending = submission()
    repository.get.return_value = pending
    repository.set_status.return_value = pending.model_copy(
        update={"status": ExerciseSubmissionStatus.REJECTED}
    )

    invalid = await subject.handle(9, "/reject_exercise 12")
    valid = await subject.handle(9, "/reject_exercise 12 Ya existe")

    assert "Usa /approve_exercise" in invalid.messages[0]
    repository.set_status.assert_awaited_once_with(
        12,
        ExerciseSubmissionStatus.PENDING,
        ExerciseSubmissionStatus.REJECTED,
        reviewed_by=9,
        moderation_notes="Ya existe",
    )
    assert valid.notification is not None
    assert "Ya existe" in valid.notification.text


@pytest.mark.asyncio
async def test_approval_reports_unconfigured_publisher() -> None:
    repository = AsyncMock()
    subject = ExerciseModerationService(repository, AsyncMock(), None, {9})

    reply = await subject.handle(9, "/approve_exercise 12")

    assert "no está configurada" in reply.messages[0]
    repository.get.assert_not_awaited()
