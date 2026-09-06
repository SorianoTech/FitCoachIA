from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

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

    with pytest.raises(InterviewerResultError, match="non-text"):
        await chain.respond("Hola", [])


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
