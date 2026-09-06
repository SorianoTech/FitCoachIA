from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from fitcoach.domain.conversation import ConversationMessage
from fitcoach.service.agent.interviewer_chain import InterviewerChain


@pytest.fixture
def model() -> MagicMock:
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=AIMessage(content="  Hola  "))
    return model


@pytest.mark.asyncio
async def test_responds_with_composed_prompt_history_and_user_message(model: MagicMock) -> None:
    chain = InterviewerChain(model)
    history = [
        ConversationMessage(1, "user", "Me llamo Ana", datetime.now(UTC)),
        ConversationMessage(1, "assistant", "Encantado, Ana", datetime.now(UTC)),
    ]

    result = await chain.respond("Quiero perder grasa", history)

    assert result == "Hola"
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
async def test_returns_empty_string_when_model_response_is_not_text(model: MagicMock) -> None:
    model.ainvoke.return_value = AIMessage(content=[{"type": "text", "text": "Hola"}])
    chain = InterviewerChain(model)

    result = await chain.respond("Hola", [])

    assert result == ""
