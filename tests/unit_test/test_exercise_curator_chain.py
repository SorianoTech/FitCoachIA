import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from fitcoach.infrastructure.config.settings import IASettings
from fitcoach.service.agent.exercise_curator_chain import (
    ExerciseCuratorChain,
    build_exercise_curator_model,
)


def proposal_payload() -> dict[str, object]:
    return {
        "status": "proposal",
        "reply": "He preparado la propuesta.",
        "proposal": {
            "name": "backpack row",
            "category": "back",
            "body_part": "back",
            "equipment": "body weight",
            "target": "lats",
            "secondary_muscles": ["biceps"],
            "instructions_en": "Hold the backpack securely, hinge forward, and row toward the torso.",
            "quality": {
                "validity": "valid",
                "confidence": 0.91,
                "rationale": "It is a coherent loaded horizontal pulling movement.",
                "safety_notes": ["Keep the spine neutral and secure the backpack."],
            },
        },
    }


@pytest.mark.asyncio
async def test_proposes_a_strict_validated_exercise() -> None:
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=AIMessage(content=json.dumps(proposal_payload())))

    reply = await ExerciseCuratorChain(model, "curator-test").propose("Remo con mochila")

    assert reply.turn.status == "proposal"
    assert reply.turn.proposal is not None
    assert reply.turn.proposal.target == "lats"
    assert reply.turn.proposal.quality.validity == "valid"
    messages = model.ainvoke.await_args.args[0]
    assert isinstance(messages[0], SystemMessage)
    assert "Allowed equipment:" in messages[0].content
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content.endswith("Remo con mochila")


def test_builds_model_with_curator_specific_settings() -> None:
    settings = IASettings.model_validate({
        "base_url": "http://localhost:9999",
        "token": "test",
        "model": "general",
        "temperature": 0.8,
        "exercise_curator_model": "curator",
        "exercise_curator_temperature": 0.1,
        "exercise_curator_max_tokens": 777,
        "exercise_curator_timeout": 12,
    })

    model = build_exercise_curator_model(settings)
    payload = model._get_request_payload([("human", "test")])

    assert model.model_name == "curator"
    assert model.max_tokens == 777
    assert model.request_timeout == 12
    assert payload["temperature"] == 0.1
    assert payload["response_format"]["json_schema"]["name"] == "ExerciseCuratorTurn"
