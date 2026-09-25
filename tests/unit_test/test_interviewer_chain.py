from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from fitcoach.domain.agent_errors import AgentError, AgentErrorCode
from fitcoach.domain.conversation import ConversationMessage
from fitcoach.service.agent.interviewer_chain import InterviewerChain, InterviewerResultError


@pytest.fixture
def model() -> MagicMock:
    model = MagicMock()
    model.ainvoke = AsyncMock(
        return_value=AIMessage(content='{"status":"in_progress","reply":"Hola"}')
    )
    return model


@pytest.mark.asyncio
async def test_responds_with_composed_prompt_history_and_user_message(model: MagicMock) -> None:
    chain = InterviewerChain(model)
    history = [
        ConversationMessage(1, "user", "Me llamo Ana", datetime.now(UTC)),
        ConversationMessage(1, "assistant", "Encantado, Ana", datetime.now(UTC)),
    ]

    reply = await chain.respond("Quiero perder grasa", history)

    assert reply.turn.reply == "Hola"
    model.ainvoke.assert_awaited_once()
    messages = model.ainvoke.await_args.args[0]
    assert isinstance(messages[0], SystemMessage)
    assert 'Interviewer ("Secretario")' in messages[0].content
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == "Me llamo Ana"
    assert isinstance(messages[2], AIMessage)
    assert messages[2].content == "Encantado, Ana"
    assert isinstance(messages[3], HumanMessage)
    assert messages[3].content == "Quiero perder grasa"


@pytest.mark.asyncio
async def test_raises_when_model_response_is_not_text(model: MagicMock) -> None:
    model.ainvoke.return_value = AIMessage(content=[{"type": "text", "text": "Hola"}])
    chain = InterviewerChain(model)

    with pytest.raises(InterviewerResultError) as exc_info:
        await chain.respond("Hola", [])

    assert exc_info.value.code is AgentErrorCode.INVALID_OUTPUT


@pytest.mark.asyncio
async def test_repairs_an_invalid_result_once(model: MagicMock) -> None:
    model.ainvoke.side_effect = [
        AIMessage(content="not json"),
        AIMessage(content='{"status":"in_progress","reply":"¿Cuál es tu objetivo?"}'),
    ]
    chain = InterviewerChain(model)

    reply = await chain.respond("Hola", [])

    assert reply.turn.reply == "¿Cuál es tu objetivo?"
    assert model.ainvoke.await_count == 2
    repair_prompt = model.ainvoke.await_args_list[1].args[0][0].content
    assert "JSON schema" in repair_prompt


class TestTokenUsageCapture:
    @pytest.mark.asyncio
    async def test_extracts_usage_from_langchain_usage_metadata(self, model: MagicMock) -> None:
        model.ainvoke.return_value = AIMessage(
            content='{"status":"in_progress","reply":"Hola"}',
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
        chain = InterviewerChain(model, model_name="gpt-test")

        reply = await chain.respond("Hola", [])

        assert len(reply.token_usages) == 1
        assert reply.token_usages[0].model == "gpt-test"
        assert reply.token_usages[0].prompt_tokens == 10
        assert reply.token_usages[0].completion_tokens == 5
        assert reply.token_usages[0].total_tokens == 15
        assert reply.token_usages[0].status == "success"
        assert reply.token_usages[0].latency_ms >= 0

    @pytest.mark.asyncio
    async def test_falls_back_to_raw_openai_token_usage(self, model: MagicMock) -> None:
        model.ainvoke.return_value = AIMessage(
            content='{"status":"in_progress","reply":"Hola"}',
            response_metadata={
                "token_usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}
            },
        )
        chain = InterviewerChain(model, model_name="gpt-test")

        reply = await chain.respond("Hola", [])

        assert len(reply.token_usages) == 1
        assert reply.token_usages[0].model == "gpt-test"
        assert reply.token_usages[0].prompt_tokens == 8
        assert reply.token_usages[0].completion_tokens == 4
        assert reply.token_usages[0].total_tokens == 12
        assert reply.token_usages[0].status == "success"
        assert reply.token_usages[0].latency_ms >= 0

    @pytest.mark.asyncio
    async def test_records_a_usage_entry_for_the_repair_call_too(self, model: MagicMock) -> None:
        model.ainvoke.side_effect = [
            AIMessage(
                content="not json",
                usage_metadata={"input_tokens": 20, "output_tokens": 3, "total_tokens": 23},
            ),
            AIMessage(
                content='{"status":"in_progress","reply":"reparado"}',
                usage_metadata={"input_tokens": 30, "output_tokens": 6, "total_tokens": 36},
            ),
        ]
        chain = InterviewerChain(model, model_name="gpt-test")

        reply = await chain.respond("Hola", [])

        assert len(reply.token_usages) == 2
        assert reply.token_usages[0].total_tokens == 23
        assert reply.token_usages[1].total_tokens == 36
        assert reply.token_usages[0].status == AgentErrorCode.INVALID_OUTPUT.value
        assert reply.token_usages[1].status == "success"
        assert reply.token_usages[0].latency_ms >= 0
        assert reply.token_usages[1].latency_ms >= 0

    @pytest.mark.asyncio
    async def test_is_empty_when_the_model_reports_no_usage(self, model: MagicMock) -> None:
        chain = InterviewerChain(model)

        reply = await chain.respond("Hola", [])

        assert reply.token_usages == []


def _api_status_error(
    error_type: type[openai.APIStatusError], status_code: int
) -> openai.APIStatusError:
    response = httpx.Response(
        status_code,
        request=httpx.Request("POST", "https://example.invalid/v1/chat/completions"),
    )
    return error_type("provider error", response=response, body={})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            openai.LengthFinishReasonError(completion=MagicMock()),
            AgentErrorCode.OUTPUT_LIMIT,
        ),
        (
            _api_status_error(openai.AuthenticationError, 401),
            AgentErrorCode.AUTHENTICATION,
        ),
        (
            _api_status_error(openai.PermissionDeniedError, 403),
            AgentErrorCode.AUTHENTICATION,
        ),
        (
            _api_status_error(openai.RateLimitError, 429),
            AgentErrorCode.RATE_LIMITED,
        ),
        (
            _api_status_error(openai.BadRequestError, 400),
            AgentErrorCode.INVALID_REQUEST,
        ),
        (
            _api_status_error(openai.APIStatusError, 402),
            AgentErrorCode.QUOTA,
        ),
        (
            _api_status_error(openai.InternalServerError, 503),
            AgentErrorCode.UNAVAILABLE,
        ),
        (
            openai.APITimeoutError(
                request=httpx.Request("POST", "https://example.invalid/v1/chat/completions")
            ),
            AgentErrorCode.TIMEOUT,
        ),
        (
            openai.APIConnectionError(
                request=httpx.Request("POST", "https://example.invalid/v1/chat/completions")
            ),
            AgentErrorCode.UNAVAILABLE,
        ),
    ],
)
async def test_maps_openai_failures_to_safe_error_codes(
    model: MagicMock, error: Exception, expected_code: AgentErrorCode
) -> None:
    model.ainvoke.side_effect = error
    chain = InterviewerChain(model)

    with pytest.raises(AgentError) as exc_info:
        await chain.respond("Hola", [])

    assert exc_info.value.code is expected_code
