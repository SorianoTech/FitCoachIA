from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from fitcoach.domain.conversation import ConversationMessage
from fitcoach.domain.interviewer_errors import InterviewerError, InterviewerErrorCode
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

    result = await chain.respond("Quiero perder grasa", history)

    assert result.reply == "Hola"
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

    assert exc_info.value.code is InterviewerErrorCode.INVALID_OUTPUT


@pytest.mark.asyncio
async def test_repairs_an_invalid_result_once(model: MagicMock) -> None:
    model.ainvoke.side_effect = [
        AIMessage(content="not json"),
        AIMessage(content='{"status":"in_progress","reply":"¿Cuál es tu objetivo?"}'),
    ]
    chain = InterviewerChain(model)

    result = await chain.respond("Hola", [])

    assert result.reply == "¿Cuál es tu objetivo?"
    assert model.ainvoke.await_count == 2
    repair_prompt = model.ainvoke.await_args_list[1].args[0][0].content
    assert "JSON schema" in repair_prompt


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
            InterviewerErrorCode.OUTPUT_LIMIT,
        ),
        (
            _api_status_error(openai.AuthenticationError, 401),
            InterviewerErrorCode.AUTHENTICATION,
        ),
        (
            _api_status_error(openai.PermissionDeniedError, 403),
            InterviewerErrorCode.AUTHENTICATION,
        ),
        (
            _api_status_error(openai.RateLimitError, 429),
            InterviewerErrorCode.RATE_LIMITED,
        ),
        (
            _api_status_error(openai.BadRequestError, 400),
            InterviewerErrorCode.INVALID_REQUEST,
        ),
        (
            _api_status_error(openai.APIStatusError, 402),
            InterviewerErrorCode.QUOTA,
        ),
        (
            _api_status_error(openai.InternalServerError, 503),
            InterviewerErrorCode.UNAVAILABLE,
        ),
        (
            openai.APITimeoutError(
                request=httpx.Request("POST", "https://example.invalid/v1/chat/completions")
            ),
            InterviewerErrorCode.TIMEOUT,
        ),
        (
            openai.APIConnectionError(
                request=httpx.Request("POST", "https://example.invalid/v1/chat/completions")
            ),
            InterviewerErrorCode.UNAVAILABLE,
        ),
    ],
)
async def test_maps_openai_failures_to_safe_error_codes(
    model: MagicMock, error: Exception, expected_code: InterviewerErrorCode
) -> None:
    model.ainvoke.side_effect = error
    chain = InterviewerChain(model)

    with pytest.raises(InterviewerError) as exc_info:
        await chain.respond("Hola", [])

    assert exc_info.value.code is expected_code
