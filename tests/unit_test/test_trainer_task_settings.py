import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.trainer_plan import TrainingPlan
from fitcoach.infrastructure.config.settings import IASettings
from fitcoach.service.agent.trainer_chain import TrainerChain, build_trainer_model
from tests.unit_test.conftest import build_plan_payload


def _settings(**overrides: object) -> IASettings:
    return IASettings.model_validate({
        "base_url": "http://localhost:9999",
        "token": "test",
        "model": "base",
        "temperature": 0.5,
        **overrides,
    })


@pytest.mark.parametrize("task", ["generation", "consultation", "extraction"])
def test_task_defaults_preserve_existing_model_and_budgets(task: str) -> None:
    settings = _settings()
    model = build_trainer_model(settings, task)
    assert model.model_name == "base"
    assert model.max_tokens == 4096
    assert model.request_timeout == 60
    assert model.max_retries == 0
    assert model.temperature == 0.5


@pytest.mark.parametrize("task", ["generation", "consultation", "extraction"])
@pytest.mark.parametrize("value", [0.0, 1.0, 2.0, "default"])
def test_temperature_override_only_affects_selected_task(task: str, value: object) -> None:
    settings = _settings(**{f"trainer_{task}_temperature": value})
    for candidate in ("generation", "consultation", "extraction"):
        model = build_trainer_model(settings, candidate)
        payload = model._get_request_payload([("human", "test")])
        if candidate == task and value == "default":
            assert "temperature" not in payload
        else:
            assert payload["temperature"] == (value if candidate == task else 0.5)


@pytest.mark.parametrize("value", [-0.1, 2.1, "invalid", "", float("inf"), float("nan")])
@pytest.mark.parametrize("task", ["generation", "consultation", "extraction"])
def test_invalid_temperature_override_fails(task: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _settings(**{f"trainer_{task}_temperature": value})


def test_temperature_default_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ia_trainer_generation_temperature", "default")
    monkeypatch.setenv("ia_trainer_consultation_temperature", "0")
    settings = IASettings(
        _env_file=None,
        base_url="http://localhost:9999",
        token="test",  # noqa: S106
        model="base",
        temperature=0.2,
    )
    assert settings.trainer_generation_temperature == "default"
    assert settings.trainer_consultation_temperature == 0


def test_overrides_are_isolated_and_consultation_has_its_own_schema() -> None:
    settings = _settings(
        trainer_generation_model="plans",
        trainer_consultation_model="fast",
        trainer_consultation_max_tokens=900,
        trainer_consultation_timeout=20,
        trainer_extraction_model="extract",
        trainer_extraction_max_tokens=1200,
        trainer_extraction_timeout=25,
    )
    generation = build_trainer_model(settings)
    consultation = build_trainer_model(settings, "consultation")
    extraction = build_trainer_model(settings, "extraction")
    assert generation.model_name == "plans"
    assert generation.max_tokens == 4096
    assert consultation.model_name == "fast"
    assert consultation.max_tokens == 900
    assert consultation.request_timeout == 20
    assert (
        consultation.model_kwargs["response_format"]["json_schema"]["name"] == "TrainerAnswerTurn"
    )
    assert extraction.model_name == "extract"
    assert extraction.max_tokens == 1200
    assert extraction.request_timeout == 25


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("trainer_consultation_model", ""),
        ("trainer_extraction_model", ""),
        ("trainer_generation_model", ""),
        ("trainer_consultation_max_tokens", 0),
        ("trainer_extraction_max_tokens", -1),
        ("trainer_consultation_timeout", 0),
        ("trainer_extraction_timeout", -1),
    ],
)
def test_invalid_task_settings_fail_validation(name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _settings(**{name: value})


@pytest.mark.asyncio
async def test_consultation_uses_selected_model_and_preserves_usage_model(
    profile: InterviewerProfile,
) -> None:
    generation = AsyncMock()
    consultation = AsyncMock()
    consultation.ainvoke.return_value = AIMessage(
        content=json.dumps({"status": "answer", "reply": "Respuesta", "intent": "answer"}),
        usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    )
    chain = TrainerChain(
        generation, "plans", consultation_model=consultation, consultation_model_name="fast"
    )
    reply = await chain.answer(
        "¿Por qué?", TrainingPlan.model_validate(build_plan_payload()), [], profile
    )
    consultation.ainvoke.assert_awaited_once()
    generation.ainvoke.assert_not_awaited()
    assert reply.token_usages[0].model == "fast"
