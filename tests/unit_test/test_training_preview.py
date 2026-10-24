import pytest

from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.trainer_plan import TrainingPlan
from fitcoach.domain.training_lifecycle import SwapOption, SwapRequest, TrainingWorkflow
from fitcoach.service.training_preview import details, preview
from tests.unit_test.conftest import build_plan_payload


def _workflow() -> TrainingWorkflow:
    return TrainingWorkflow(
        id=1,
        kind="renewal",
        base_plan_id=2,
        state="awaiting_confirmation",
        draft=TrainingPlan.model_validate(build_plan_payload()),
        report="A long model report",
        answers={"interpretation": "A long interpreted review"},
    )


def test_preview_is_one_readable_card_from_the_prescription() -> None:
    workflow = _workflow()
    text = preview(workflow)
    assert "TU SIGUIENTE MESOCICLO" in text
    assert "Ganar músculo" in text
    assert "3 días/semana" in text
    assert "barbell bench press · 3 × 8-10" in text
    assert "S4 · Descarga · 9 series · RPE máx. 7" in text
    assert "A long model report" not in text
    assert "A long interpreted review" not in text
    assert "Contexto propuesto" not in text
    assert "Borrador 1" not in text
    assert len(text) < 4096
    assert "\n\n" in text


def test_details_preserve_all_weeks_report_review_and_constraints(
    profile: InterviewerProfile,
) -> None:
    workflow = _workflow()
    workflow.effective_profile = profile
    plan_before = workflow.draft.model_dump_json()
    messages = details(workflow)
    text = "\n".join(messages)
    for number in range(1, 5):
        assert f"SEMANA {number}" in text
    assert "descanso 120s" in text
    assert "A long model report" in text
    assert "A long interpreted review" in text
    assert "DATOS QUE HEMOS TENIDO EN CUENTA" in text
    assert messages[-1] == preview(workflow)
    assert workflow.draft.model_dump_json() == plan_before


def test_preview_maximal_plan_fits_one_telegram_message(profile: InterviewerProfile) -> None:
    workflow = _workflow()
    workflow.draft = TrainingPlan.model_validate(build_plan_payload(days_per_week=7))
    for week in workflow.draft.weeks:
        for day in week.days:
            day.exercises = [
                day.exercises[0].model_copy(
                    update={"name": "an exercise with a very long name " * 20}
                )
                for _ in range(8)
            ]
            day.focus = "a very long training focus " * 20
    workflow.effective_profile = profile.model_copy(
        update={
            "flags": profile.flags.model_copy(update={"red": ["professional clearance needed"]}),
        }
    )
    text = preview(workflow)
    assert len(text) <= 4096
    assert "Consulta a un profesional" in text
    assert "+ 5 ejercicios más" in text
    assert "Tu plan vigente no cambia" in text


def test_missing_draft_is_rejected() -> None:
    workflow = _workflow()
    workflow.draft = None
    with pytest.raises(ValueError, match="draft"):
        preview(workflow)
    with pytest.raises(ValueError, match="draft"):
        details(workflow)


def test_swap_preview_only_shows_selected_alternative() -> None:
    workflow = _workflow()
    workflow.kind = "exercise_swap"
    workflow.swap = SwapRequest(exercise_id=100, from_week=2, reason="preference")
    chosen = workflow.draft.weeks[1].days[0].exercises[0]
    other = chosen.model_copy(update={"exercise_id": chosen.exercise_id + 1})
    workflow.draft.weeks[1].days[1].exercises[0] = other
    workflow.options = [
        SwapOption(exercise=chosen, rationale="Selected rationale"),
        SwapOption(exercise=other, rationale="Unselected rationale"),
    ]
    workflow.answers["selected_exercise_id"] = str(chosen.exercise_id)
    text = preview(workflow)
    assert "TU CAMBIO DE EJERCICIO" in text
    assert "Selected rationale" in text
    assert "Unselected rationale" not in text
    assert "desde la semana 2" in text
    assert "SESIÓN" not in text


def test_unicode_preview_is_bounded_and_explicit_when_shortened(
    profile: InterviewerProfile,
) -> None:
    workflow = _workflow()
    workflow.draft = TrainingPlan.model_validate(build_plan_payload(days_per_week=7))
    for week in workflow.draft.weeks:
        for day in week.days:
            day.focus = "🏋" * 100
            day.exercises = [
                day.exercises[0].model_copy(update={"name": "🏋" * 100}) for _ in range(8)
            ]
    workflow.effective_profile = profile.model_copy(
        update={
            "flags": profile.flags.model_copy(update={"red": ["professional clearance needed"]}),
        }
    )
    text = preview(workflow)
    assert len(text.encode("utf-16-le")) // 2 <= 4096
    assert "Hay más información" in text
    assert "Consulta a un profesional" in text
    assert "Tu plan vigente no cambia" in text
