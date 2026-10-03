import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.trainer_plan import TrainingPlan
from fitcoach.domain.training_lifecycle import (
    SwapRequest,
    TrainingAdaptationContext,
    TrainingReview,
)
from fitcoach.service.agent.llm_chain import InvalidModelOutputError
from fitcoach.service.agent.trainer_chain import TrainerChain
from fitcoach.service.agent.training_adaptation_chain import TrainingAdaptationChain
from tests.fixtures.stub_server import _renewal_turn
from tests.unit_test.conftest import build_plan_payload


@pytest.mark.asyncio
async def test_review_extracts_only_training_patch(profile: InterviewerProfile) -> None:
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content=json.dumps({
            "profile_patch": {},
            "safety_hold": False,
            "explanation": "Sin cambios",
        })
    )
    reply = await TrainingAdaptationChain(model, AsyncMock()).extract_review(
        profile, {"results": "mejora"}
    )
    assert reply.result.profile_patch.apply(profile) == profile
    assert not reply.result.safety_hold


@pytest.mark.asyncio
async def test_swap_rejects_invented_ids_after_one_repair(profile: InterviewerProfile) -> None:
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content=json.dumps({
            "options": [
                {
                    "exercise": {
                        "exercise_id": 999,
                        "name": "invented",
                        "sets": 3,
                        "reps": "8",
                        "rest_seconds": 60,
                    },
                    "rationale": "variation",
                }
            ],
        })
    )
    chain = TrainingAdaptationChain(AsyncMock(), model)
    with pytest.raises(InvalidModelOutputError):
        await chain.propose_swap(
            profile,
            SwapRequest(exercise_id=1, from_week=2, reason="material"),
            Exercise(1, "press"),
            [Exercise(2, "other press")],
        )
    assert model.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_swap_includes_affected_sessions_weekly_volume_and_source_instructions(
    profile: InterviewerProfile,
) -> None:
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content=json.dumps({
            "safety_hold": False,
            "options": [
                {
                    "exercise": {
                        "exercise_id": 202,
                        "name": "push up",
                        "sets": 3,
                        "reps": "8-10",
                        "rest_seconds": 120,
                        "rpe": 7.0,
                    },
                    "rationale": "Similar pressing function",
                }
            ],
        })
    )
    plan = TrainingPlan.model_validate(build_plan_payload())
    source = Exercise(
        101,
        "barbell bench press",
        target="pectorals",
        instructions_en="Press the bar from the chest.",
    )
    reply = await TrainingAdaptationChain(AsyncMock(), model).propose_swap(
        profile,
        SwapRequest(exercise_id=101, from_week=2, reason="variation"),
        source,
        [Exercise(202, "push up")],
        plan,
        catalogue=[source],
    )
    assert len(reply.result.options) == 1
    data = json.loads(model.ainvoke.await_args.args[0][1].content)
    assert {item["week"] for item in data["affected_sessions"]} == {2, 3, 4}
    assert data["affected_sessions"][0]["session"] == plan.weeks[1].days[0].model_dump(mode="json")
    assert data["prescribed_weekly_sets_by_target"]["2"]["pectorals"] == 9
    assert data["source"]["instructions_en"] == source.instructions_en
    assert data["session_exercise_metadata"][0]["target"] == "pectorals"


@pytest.mark.asyncio
async def test_swap_request_extraction_uses_separate_schema_and_canonical_equipment(
    profile: InterviewerProfile,
) -> None:
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content=json.dumps({
            "excluded_equipment": ["barbell"],
            "safety_hold": False,
            "clarification": None,
        })
    )
    chain = TrainingAdaptationChain(AsyncMock(), AsyncMock(), request_model=model)
    reply = await chain.extract_swap_constraints(
        profile, SwapRequest(exercise_id=101, from_week=2, reason="sin barra, no tengo dolor")
    )
    assert reply.result.excluded_equipment == ["barbell"]
    assert not reply.result.safety_hold
    data = json.loads(model.ainvoke.await_args.args[0][1].content)
    assert "barbell" in data["known_equipment"]
    assert data["request"]["reason"] == "sin barra, no tengo dolor"


@pytest.mark.asyncio
async def test_renewal_uses_profile_previous_plan_and_review(profile: InterviewerProfile) -> None:
    effective = profile.model_copy(
        update={"commitment": profile.commitment.model_copy(update={"days_per_week": 1})}
    )
    turn = _renewal_turn()
    plan = TrainingPlan.model_validate(turn["plan"])
    context = TrainingAdaptationContext(
        profile=effective,
        previous_plan=plan,
        previous_version=4,
        review=TrainingReview(
            adherence="todas",
            results="mejoras",
            recovery="buena",
            discomfort="sin molestias",
            preferences="mantener",
            changes="sin cambios",
        ),
        prescribed_summary={"1": {"pectorals": 3}},
    )
    catalogue = [
        Exercise(1, "barbell bench press", target="pectorals", equipment="barbell"),
        Exercise(2, "barbell row", target="lats", equipment="barbell"),
        Exercise(3, "back squat", target="quads", equipment="barbell"),
    ]
    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(content=json.dumps(turn))
    result = await TrainerChain(model).generate_next_plan(context, catalogue)
    assert result.turn.plan == plan
    messages = model.ainvoke.await_args.args[0]
    assert "previous_version" in messages[1].content
    assert "mejoras" in messages[1].content
    assert result.trace is not None
    turn["plan"]["weeks"][3]["days"][0]["exercises"][0]["rpe"] = 9.0
    model.ainvoke.return_value = AIMessage(content=json.dumps(turn))
    with pytest.raises(InvalidModelOutputError):
        await TrainerChain(model).generate_next_plan(context, catalogue)
    assert model.ainvoke.await_count == 3
