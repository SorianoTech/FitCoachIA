import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.training_lifecycle import SwapRequest
from fitcoach.service.agent.llm_chain import InvalidModelOutputError
from fitcoach.service.agent.training_adaptation_chain import TrainingAdaptationChain


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
