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
from fitcoach.domain.trainer_plan import TrainingPlan
from fitcoach.service.agent.llm_chain import InvalidModelOutputError
from fitcoach.service.agent.trainer_chain import TrainerChain
from tests.unit_test.conftest import build_plan_payload


def _plan_json(exercise_id: int = 101) -> str:
    return json.dumps({
        "status": "plan",
        "reply": "Aquí tienes tu plan",
        "report": "Plan de 4 semanas, 3 días",
        "plan": build_plan_payload(exercise_id=exercise_id),
    })


@pytest.fixture
def model() -> MagicMock:
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=AIMessage(content=_plan_json()))
    return model


class TestGeneratePlan:
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
        reply = await TrainerChain(model).generate_plan(profile, exercises)

        assert reply.turn.plan is not None
        assert len(reply.turn.plan.weeks) == 4
        assert reply.turn.plan.exercise_ids() == {101}

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
        repair_prompt = model.ainvoke.await_args_list[1].args[0][0].content
        assert "JSON schema" in repair_prompt

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
        self, model: MagicMock, exercises: list[Exercise]
    ) -> None:
        model.ainvoke.return_value = AIMessage(
            content='{"status":"answer","reply":"Porque progresas mejor"}'
        )
        plan = TrainingPlan.model_validate(build_plan_payload())
        history = [
            ConversationMessage(1, "user", "¿Por qué tres días?", datetime.now(UTC)),
            ConversationMessage(1, "assistant", "Por tu compromiso", datetime.now(UTC)),
        ]

        reply = await TrainerChain(model).answer("¿Y el descanso?", plan, history, exercises)

        assert reply.turn.reply == "Porque progresas mejor"
        messages = model.ainvoke.await_args.args[0]
        assert isinstance(messages[0], SystemMessage)
        assert "gain_muscle" in messages[1].content  # el plan vigente
        assert messages[2].content == "¿Por qué tres días?"
        assert messages[3].content == "Por tu compromiso"
        assert messages[4].content == "¿Y el descanso?"


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
