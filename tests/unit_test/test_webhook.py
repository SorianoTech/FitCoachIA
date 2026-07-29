from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from telegram import Bot

from fitcoach.api.webhook import (
    INVALID_TEXT_MESSAGE,
    WELCOME_MESSAGE,
    remove_emojis,
    webhook,
)
from fitcoach.infrastructure.bot.telegram_bot import get_bot
from fitcoach.main import app as fitcoach_app
from fitcoach.service.llm.llm_caller import LLM, get_llm


@pytest.fixture
def mock_bot() -> AsyncMock:
    return AsyncMock(spec=Bot)


@pytest.fixture
def mock_llm() -> AsyncMock:
    return AsyncMock(spec=LLM)


@pytest.fixture
def client(mock_bot: AsyncMock, mock_llm: AsyncMock) -> TestClient:
    app = FastAPI()
    app.include_router(webhook)
    app.dependency_overrides[get_bot] = lambda: mock_bot
    app.dependency_overrides[get_llm] = lambda: mock_llm
    return TestClient(app)


def _text_update(chat_id: int, text: str) -> dict[str, object]:
    return {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "date": 0,
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    }


def _edited_text_update(chat_id: int, text: str | None = None) -> dict[str, object]:
    message: dict[str, object] = {
        "message_id": 12,
        "date": 0,
        "edit_date": 1,
        "chat": {"id": chat_id, "type": "private"},
    }
    if text is not None:
        message["text"] = text
    return {"update_id": 4, "edited_message": message}


class TestRemoveEmojis:
    def test_returns_text_unchanged_when_it_has_no_emojis(self) -> None:
        assert remove_emojis("hola mundo") == "hola mundo"

    def test_removes_emoji_and_collapses_leftover_whitespace(self) -> None:
        assert remove_emojis("hola 👋 mundo") == "hola mundo"

    def test_keeps_punctuation_and_symbols(self) -> None:
        # El espacio que separaba el emoji se conserva: "Hola 👋," -> "Hola ,".
        assert remove_emojis("¡Hola 👋, 100% listo (€5)!") == "¡Hola , 100% listo (€5)!"

    def test_keeps_accented_letters(self) -> None:
        assert remove_emojis("entrenamiento físico mañana 💪") == "entrenamiento físico mañana"

    def test_removes_emoji_presentable_symbols(self) -> None:
        # Extended_Pictographic incluye © ® ™: se eliminan por diseño.
        assert remove_emojis("Copyright © 2024 Fit™ ®") == "Copyright 2024 Fit"

    def test_keeps_non_pictographic_symbols(self) -> None:
        assert remove_emojis("flecha → y suma +") == "flecha → y suma +"

    def test_removes_multi_codepoint_emoji(self) -> None:
        # Familia con ZWJ y bandera con indicadores regionales.
        assert remove_emojis("familia 👨‍👩‍👧 en 🇪🇸") == "familia en"

    def test_removes_keycap_sequence_but_keeps_the_digit(self) -> None:
        assert remove_emojis("serie 1️⃣") == "serie 1"

    def test_strips_surrounding_whitespace(self) -> None:
        assert remove_emojis("  🔥 hola 🔥  ") == "hola"

    def test_returns_empty_string_when_text_is_only_emojis(self) -> None:
        assert remove_emojis("👋🔥💪") == ""

    def test_returns_empty_string_when_text_is_only_whitespace(self) -> None:
        assert remove_emojis("   \t\n  ") == ""

    def test_returns_empty_string_when_text_is_empty(self) -> None:
        assert remove_emojis("") == ""


class TestTelegramWebhook:
    def test_start_command_replies_with_welcome_message(
        self, client: TestClient, mock_bot: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json=_text_update(123, "/start"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=123, message_thread_id=None, text=WELCOME_MESSAGE
        )

    def test_free_text_message_replies_with_the_agent_llm_output(
        self, client: TestClient, mock_bot: AsyncMock, mock_llm: AsyncMock
    ) -> None:
        mock_llm.chat.return_value = "agent reply"

        response = client.post("/webhook/response", json=_text_update(456, "hola"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_llm.chat.assert_awaited_once()
        sent_messages = mock_llm.chat.await_args.kwargs["messages"].get_input()
        assert sent_messages[-1] == {"role": "user", "content": "hola"}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text="agent reply"
        )

    def test_free_text_emojis_are_removed_before_reaching_the_agent(
        self, client: TestClient, mock_bot: AsyncMock, mock_llm: AsyncMock
    ) -> None:
        mock_llm.chat.return_value = "agent reply"

        response = client.post("/webhook/response", json=_text_update(456, "hola 👋 mundo 🔥"))

        assert response.status_code == 200
        sent_messages = mock_llm.chat.await_args.kwargs["messages"].get_input()
        assert sent_messages[-1] == {"role": "user", "content": "hola mundo"}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text="agent reply"
        )

    def test_interview_command_starts_the_agent_conversation(
        self, client: TestClient, mock_bot: AsyncMock, mock_llm: AsyncMock
    ) -> None:
        mock_llm.chat.return_value = "¡Bienvenido a la entrevista!"

        response = client.post("/webhook/response", json=_text_update(456, "/interview"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_llm.chat.assert_awaited_once()
        sent_messages = mock_llm.chat.await_args.kwargs["messages"].get_input()
        assert sent_messages[0]["role"] == "system"
        assert sent_messages[-1] == {
            "role": "user",
            "content": (
                "New interview conversation was initiated. "
                "What do you need to know about our new client?"
            ),
        }
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text="¡Bienvenido a la entrevista!"
        )

    def test_interview_command_propagates_llm_errors_without_replying(
        self, client: TestClient, mock_bot: AsyncMock, mock_llm: AsyncMock
    ) -> None:
        request = httpx.Request("POST", "http://test-llm:9999/v1/chat/completions")
        mock_llm.chat.side_effect = httpx.HTTPStatusError(
            "server error", request=request, response=httpx.Response(500, request=request)
        )

        with pytest.raises(httpx.HTTPStatusError):
            client.post("/webhook/response", json=_text_update(456, "/interview"))

        mock_bot.send_message.assert_not_awaited()

    def test_doubts_command_replies_with_not_implemented_yet(
        self, client: TestClient, mock_bot: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json=_text_update(456, "/doubts"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text="Option not implemented yet"
        )

    def test_progress_command_replies_with_not_implemented_yet(
        self, client: TestClient, mock_bot: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json=_text_update(456, "/progress"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text="Option not implemented yet"
        )

    def test_free_text_message_propagates_llm_errors_without_replying(
        self, client: TestClient, mock_bot: AsyncMock, mock_llm: AsyncMock
    ) -> None:
        request = httpx.Request("POST", "http://test-llm:9999/v1/chat/completions")
        mock_llm.chat.side_effect = httpx.HTTPStatusError(
            "server error", request=request, response=httpx.Response(500, request=request)
        )

        with pytest.raises(httpx.HTTPStatusError):
            client.post("/webhook/response", json=_text_update(456, "hola"))

        mock_bot.send_message.assert_not_awaited()

    def test_start_command_still_greets_when_followed_by_emoji(
        self, client: TestClient, mock_bot: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json=_text_update(123, "/start 👋"))

        assert response.status_code == 200
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=123, message_thread_id=None, text=WELCOME_MESSAGE
        )

    def test_emoji_only_message_replies_with_invalid_text(
        self, client: TestClient, mock_bot: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json=_text_update(456, "👋🔥💪"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text=INVALID_TEXT_MESSAGE
        )

    def test_whitespace_only_message_replies_with_invalid_text(
        self, client: TestClient, mock_bot: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json=_text_update(456, "   "))

        assert response.status_code == 200
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text=INVALID_TEXT_MESSAGE
        )

    def test_update_without_message_replies_with_fallback_text(
        self, client: TestClient, mock_bot: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json={"update_id": 2})

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=-1, text="I didn't receive any information. Please, send it again .... "
        )

    def test_message_without_text_replies_with_fallback_text(
        self, client: TestClient, mock_bot: AsyncMock
    ) -> None:
        update = {
            "update_id": 3,
            "message": {
                "message_id": 11,
                "date": 0,
                "chat": {"id": 789, "type": "private"},
            },
        }

        response = client.post("/webhook/response", json=update)

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=789, text="I didn't receive any information. Please, send it again .... "
        )

    def test_malformed_body_returns_400(self, client: TestClient, mock_bot: AsyncMock) -> None:
        response = client.post(
            "/webhook/response",
            content="not-json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 400
        mock_bot.send_message.assert_not_awaited()


class TestEditedMessage:
    def test_edited_message_is_processed_like_a_new_message(
        self, client: TestClient, mock_bot: AsyncMock, mock_llm: AsyncMock
    ) -> None:
        mock_llm.chat.return_value = "agent reply"

        response = client.post("/webhook/response", json=_edited_text_update(456, "hola editada"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_llm.chat.assert_awaited_once()
        sent_messages = mock_llm.chat.await_args.kwargs["messages"].get_input()
        assert sent_messages[-1] == {"role": "user", "content": "hola editada"}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text="agent reply"
        )

    def test_edited_message_without_text_replies_with_fallback_text(
        self, client: TestClient, mock_bot: AsyncMock, mock_llm: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json=_edited_text_update(789))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_llm.chat.assert_not_awaited()
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=789, text="I didn't receive any information. Please, send it again .... "
        )


class TestWebhookRouteRegistration:
    def test_webhook_response_route_is_registered_on_the_app(
        self, mock_bot: AsyncMock, mock_llm: AsyncMock
    ) -> None:
        fitcoach_app.dependency_overrides[get_bot] = lambda: mock_bot
        fitcoach_app.dependency_overrides[get_llm] = lambda: mock_llm
        try:
            response = TestClient(fitcoach_app).post(
                "/webhook/response", json=_text_update(123, "/start")
            )
        finally:
            fitcoach_app.dependency_overrides.pop(get_bot, None)
            fitcoach_app.dependency_overrides.pop(get_llm, None)

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=123, message_thread_id=None, text=WELCOME_MESSAGE
        )

    def test_webhook_response_route_only_accepts_post(self) -> None:
        response = TestClient(fitcoach_app).get("/webhook/response")

        assert response.status_code == 405
