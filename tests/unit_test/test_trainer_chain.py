import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from fitcoach.domain.agent_errors import AgentError, AgentErrorCode
from fitcoach.domain.conversation import ConversationMessage
from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.trainer_plan import TrainerTurn, TrainingPlan
from fitcoach.infrastructure.config.settings import IASettings
from fitcoach.service.agent.llm_chain import InvalidModelOutputError, strict_response_format
from fitcoach.service.agent.trainer_chain import TrainerChain, build_trainer_model
from tests.unit_test.conftest import build_plan_payload


def _plan_json(exercise_id: int = 101) -> str:
    plan = build_plan_payload(exercise_id=exercise_id)
    if exercise_id == 102:
        plan = TrainingPlan.model_validate(plan).model_dump(mode="json")
        for week in plan["weeks"]:
            for day in week["days"]:
                day["exercises"][0]["name"] = "barbell row"
    return json.dumps({
        "status": "plan",
        "reply": "Aquí tienes tu plan",
        "report": "Plan de 4 semanas, 3 días",
        "plan": plan,
    })


@pytest.fixture
def model() -> MagicMock:
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=AIMessage(content=_plan_json()))
    return model


class TestGeneratePlan:
    @pytest.mark.parametrize("failure", ["name", "equipment", "goal", "time", "duplicate"])
    @pytest.mark.asyncio
    async def test_repairs_exact_constraint_failures(
        self, model: MagicMock, profile: InterviewerProfile, exercises: list[Exercise], failure: str
    ) -> None:
        payload = json.loads(_plan_json())
        day = payload["plan"]["weeks"][0]["days"][0]
        if failure == "name":
            day["exercises"][0]["name"] = "invented name"
        elif failure == "equipment":
            from dataclasses import replace

            exercises = [replace(exercises[0], equipment="dumbbell"), exercises[1]]
        elif failure == "goal":
            payload["plan"]["goal"] = "lose_fat"
        elif failure == "time":
            day["estimated_minutes"] = 61
        else:
            day["exercises"].append(day["exercises"][0].copy())
        model.ainvoke.side_effect = [
            AIMessage(content=json.dumps(payload)),
            AIMessage(content=_plan_json(exercise_id=102)),
        ]
        reply = await TrainerChain(model).generate_plan(profile, exercises)
        assert reply.turn.plan is not None
        assert model.ainvoke.await_count == 2

    @pytest.mark.asyncio
    async def test_composes_system_prompt_rag_context_and_profile(
        self, model: MagicMock, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        chain = TrainerChain(model)

        reply = await chain.generate_plan(profile, exercises)

        assert reply.turn.status == "plan"
        messages = model.ainvoke.await_args.args[0]
        assert isinstance(messages[0], SystemMessage)
        assert 'Trainer ("Entrenador")' in messages[0].content
        # The retrieved catalogue is injected where {{rag_context}} was.
        assert "id: 101" in messages[0].content
        assert "barbell bench press" in messages[0].content
        assert "{{rag_context}}" not in messages[0].content
        assert isinstance(messages[1], HumanMessage)
        assert "name_or_username" in messages[1].content

    @pytest.mark.asyncio
    async def test_returns_the_validated_plan(
        self, model: MagicMock, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        reply = await TrainerChain(model, model_name="trace-model").generate_plan(
            profile, exercises
        )

        assert reply.turn.plan is not None
        assert len(reply.turn.plan.weeks) == 4
        assert reply.turn.plan.exercise_ids() == {101}
        assert reply.trace is not None
        assert reply.trace.model == "trace-model"
        assert reply.trace.skill_name == "trainer"
        assert len(reply.trace.prompt_hash) == 64
        assert len(reply.trace.skill_hash) == 64
        assert reply.trace.retrieved_exercise_ids == (101, 102)

    @pytest.mark.asyncio
    async def test_rejects_a_plan_using_an_exercise_that_was_not_retrieved(
        self, model: MagicMock, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        # 999 is not in the retrieved catalogue; the repair also invents one.
        model.ainvoke.side_effect = [
            AIMessage(content=_plan_json(exercise_id=999)),
            AIMessage(content=_plan_json(exercise_id=888)),
        ]
        chain = TrainerChain(model)

        with pytest.raises(InvalidModelOutputError) as exc_info:
            await chain.generate_plan(profile, exercises)

        assert exc_info.value.code is AgentErrorCode.INVALID_OUTPUT
        assert model.ainvoke.await_count == 2

    @pytest.mark.asyncio
    async def test_repairs_an_invented_exercise_id_once(
        self, model: MagicMock, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        model.ainvoke.side_effect = [
            AIMessage(content=_plan_json(exercise_id=999)),
            AIMessage(content=_plan_json(exercise_id=102)),
        ]

        reply = await TrainerChain(model).generate_plan(profile, exercises)

        assert reply.turn.plan is not None
        assert reply.turn.plan.exercise_ids() == {102}
        repair_messages = model.ainvoke.await_args_list[1].args[0]
        # The repair keeps the original system prompt, so the catalogue is still there.
        assert isinstance(repair_messages[0], SystemMessage)
        assert "id: 102" in repair_messages[0].content
        assert isinstance(repair_messages[-2], AIMessage)
        assert '"exercise_id": 999' in repair_messages[-2].content
        assert "JSON schema" in repair_messages[-1].content
        assert "999" in repair_messages[-1].content

    @pytest.mark.asyncio
    async def test_repairs_malformed_json_once(
        self, model: MagicMock, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        model.ainvoke.side_effect = [
            AIMessage(content="not json at all"),
            AIMessage(content=_plan_json()),
        ]

        reply = await TrainerChain(model).generate_plan(profile, exercises)

        assert reply.turn.status == "plan"
        assert model.ainvoke.await_count == 2

    @pytest.mark.asyncio
    async def test_accepts_an_answer_turn_without_checking_exercise_ids(
        self, model: MagicMock, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        model.ainvoke.return_value = AIMessage(
            content='{"status":"answer","reply":"El catálogo no está disponible"}'
        )

        reply = await TrainerChain(model).generate_plan(profile, exercises)

        assert reply.turn.status == "answer"
        assert reply.turn.plan is None


class TestAnswer:
    @pytest.mark.asyncio
    async def test_sends_plan_history_and_question(
        self, model: MagicMock, profile: InterviewerProfile
    ) -> None:
        model.ainvoke.return_value = AIMessage(
            content='{"status":"answer","reply":"Porque progresas mejor"}'
        )
        plan = TrainingPlan.model_validate(build_plan_payload())
        history = [
            ConversationMessage(1, "user", "¿Por qué tres días?", datetime.now(UTC)),
            ConversationMessage(1, "assistant", "Por tu compromiso", datetime.now(UTC)),
        ]

        reply = await TrainerChain(model).answer("¿Y el descanso?", plan, history, profile)

        assert reply.turn.reply == "Porque progresas mejor"
        messages = model.ainvoke.await_args.args[0]
        assert isinstance(messages[0], SystemMessage)
        assert "read-only" in messages[0].content
        assert "rag_context" not in messages[0].content
        assert "<skill>" not in messages[0].content
        assert "PLAN STRUCTURE" not in messages[0].content
        assert messages[1].content == "¿Por qué tres días?"
        assert messages[2].content == "Por tu compromiso"
        assert plan.model_dump_json() in messages[3].content
        assert profile.model_dump_json() in messages[3].content
        assert messages[4].content == "¿Y el descanso?"
        assert reply.trace is None

    @pytest.mark.asyncio
    async def test_answers_without_a_profile(self, model: MagicMock) -> None:
        model.ainvoke.return_value = AIMessage(
            content='{"status":"answer","reply":"Descansa 120 segundos","report":null,"plan":null}'
        )
        plan = TrainingPlan.model_validate(build_plan_payload())

        reply = await TrainerChain(model).answer("¿Cuánto descanso?", plan, [])

        assert reply.turn.status == "answer"
        assert "Not available." in model.ainvoke.await_args.args[0][1].content

    @pytest.mark.asyncio
    async def test_repairs_a_plan_turn_in_read_only_mode(self, model: MagicMock) -> None:
        model.ainvoke.side_effect = [
            AIMessage(content=_plan_json()),
            AIMessage(content='{"status":"answer","reply":"No he cambiado tu plan"}'),
        ]
        plan = TrainingPlan.model_validate(build_plan_payload())

        reply = await TrainerChain(model).answer("Cambia los ejercicios", plan, [])

        assert reply.turn.status == "answer"
        assert reply.turn.plan is None
        assert model.ainvoke.await_count == 2
        repair = model.ainvoke.await_args_list[1].args[0]
        assert "read-only" in repair[0].content
        assert plan.model_dump_json() in repair[1].content
        assert "TrainerAnswerTurn" in repair[-1].content

    @pytest.mark.asyncio
    async def test_rejects_a_plan_even_after_repair(self, model: MagicMock) -> None:
        plan = TrainingPlan.model_validate(build_plan_payload())

        with pytest.raises(InvalidModelOutputError):
            await TrainerChain(model).answer("Cambia el volumen", plan, [])

        assert model.ainvoke.await_count == 2


class TestTokenUsage:
    @pytest.mark.asyncio
    async def test_captures_usage_for_the_successful_call(
        self, model: MagicMock, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        model.ainvoke.return_value = AIMessage(
            content=_plan_json(),
            usage_metadata={"input_tokens": 900, "output_tokens": 700, "total_tokens": 1600},
        )

        reply = await TrainerChain(model, model_name="gpt-test").generate_plan(profile, exercises)

        assert len(reply.token_usages) == 1
        assert reply.token_usages[0].model == "gpt-test"
        assert reply.token_usages[0].total_tokens == 1600
        assert reply.token_usages[0].status == "success"

    @pytest.mark.asyncio
    async def test_keeps_the_usage_of_the_rejected_call_and_tags_it(
        self, model: MagicMock, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        model.ainvoke.side_effect = [
            AIMessage(
                content=_plan_json(exercise_id=999),
                usage_metadata={"input_tokens": 900, "output_tokens": 700, "total_tokens": 1600},
            ),
            AIMessage(
                content=_plan_json(exercise_id=101),
                usage_metadata={"input_tokens": 100, "output_tokens": 500, "total_tokens": 600},
            ),
        ]

        reply = await TrainerChain(model, model_name="gpt-test").generate_plan(profile, exercises)

        assert len(reply.token_usages) == 2
        assert reply.token_usages[0].status == AgentErrorCode.INVALID_OUTPUT.value
        assert reply.token_usages[0].total_tokens == 1600
        assert reply.token_usages[1].status == "success"


class TestProviderErrors:
    @pytest.mark.parametrize(
        ("exception", "expected"),
        [
            (
                openai.APITimeoutError(request=httpx.Request("POST", "http://x")),
                AgentErrorCode.TIMEOUT,
            ),
            (httpx.ConnectTimeout("slow"), AgentErrorCode.TIMEOUT),
            (
                openai.APIConnectionError(request=httpx.Request("POST", "http://x")),
                AgentErrorCode.UNAVAILABLE,
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_maps_provider_exceptions_to_agent_errors(
        self,
        model: MagicMock,
        profile: InterviewerProfile,
        exercises: list[Exercise],
        exception: Exception,
        expected: AgentErrorCode,
    ) -> None:
        model.ainvoke.side_effect = exception

        with pytest.raises(AgentError) as exc_info:
            await TrainerChain(model).generate_plan(profile, exercises)

        assert exc_info.value.code is expected
        # The failed call is still accounted for.
        assert len(exc_info.value.token_usages) == 1
        assert exc_info.value.token_usages[0].status == expected.value

    @pytest.mark.asyncio
    async def test_raises_when_the_model_returns_non_text_content(
        self, model: MagicMock, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        model.ainvoke.return_value = AIMessage(content=[{"type": "text", "text": "hola"}])

        with pytest.raises(InvalidModelOutputError):
            await TrainerChain(model).generate_plan(profile, exercises)


class TestStrictResponseFormat:
    def test_trainer_model_requests_strict_json_schema_outputs(self) -> None:
        settings = IASettings(
            base_url="http://llm",
            token="test-token",  # noqa: S106
            model="m",
            temperature=0.2,
            _env_file=None,  # type: ignore[call-arg]
        )

        response_format = build_trainer_model(settings).model_kwargs["response_format"]

        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["name"] == "TrainerTurn"
        assert response_format["json_schema"]["strict"] is True

    def test_schema_satisfies_the_strict_mode_rules(self) -> None:
        schema = strict_response_format(TrainerTurn)["json_schema"]["schema"]
        objects = [schema, *schema["$defs"].values()]

        for obj in (o for o in objects if o.get("type") == "object"):
            # Strict mode: every property required, nothing extra allowed.
            assert obj["additionalProperties"] is False
            assert set(obj["required"]) == set(obj["properties"])
        assert "default" not in json.dumps(schema)

    def test_schema_pins_the_mesocycle_to_four_weeks(self) -> None:
        schema = strict_response_format(TrainerTurn)["json_schema"]["schema"]
        weeks = schema["$defs"]["TrainingPlan"]["properties"]["weeks"]

        assert weeks["minItems"] == 4
        assert weeks["maxItems"] == 4

    def test_answer_turn_with_explicit_nulls_validates(self) -> None:
        # Strict outputs always emit every key, so answers arrive with nulls.
        turn = TrainerTurn.model_validate_json(
            '{"status": "answer", "reply": "Hola", "report": null, "plan": null}'
        )

        assert turn.report is None
        assert turn.plan is None
