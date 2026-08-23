import logging
from unittest.mock import AsyncMock

import httpx
import pytest
import regex
from fastapi import FastAPI
from fastapi.testclient import TestClient
from telegram import Bot

from fitcoach.api.webhook import webhook
from fitcoach.domain.constants import Constants
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


class TestTelegramWebhook:
    def test_start_command_replies_with_welcome_message(
        self, client: TestClient, mock_bot: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json=_text_update(123, "/start"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=123, message_thread_id=None, text=Constants.WELCOME_MESSAGE
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
        assert sent_messages[-1] == {"role": "user", "content": Constants.INTERVIEW_SEED_MESSAGE}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text="¡Bienvenido a la entrevista!"
        )

    def test_interview_command_replies_with_llm_error_message_when_the_model_fails(
        self, client: TestClient, mock_bot: AsyncMock, mock_llm: AsyncMock
    ) -> None:
        request = httpx.Request("POST", "http://test-llm:9999/v1/chat/completions")
        mock_llm.chat.side_effect = httpx.HTTPStatusError(
            "server error", request=request, response=httpx.Response(500, request=request)
        )

        response = client.post("/webhook/response", json=_text_update(456, "/interview"))

        # Debe devolver 200: Telegram reenvia cualquier update sin 2xx.
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text=Constants.LLM_ERROR_MESSAGE
        )

    def test_doubts_command_replies_with_not_implemented_yet(
        self, client: TestClient, mock_bot: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json=_text_update(456, "/doubts"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text=Constants.NOT_IMPLEMENTED_MESSAGE
        )

    def test_progress_command_replies_with_not_implemented_yet(
        self, client: TestClient, mock_bot: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json=_text_update(456, "/progress"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text=Constants.NOT_IMPLEMENTED_MESSAGE
        )

    def test_free_text_message_replies_with_llm_error_message_when_the_model_fails(
        self, client: TestClient, mock_bot: AsyncMock, mock_llm: AsyncMock
    ) -> None:
        request = httpx.Request("POST", "http://test-llm:9999/v1/chat/completions")
        mock_llm.chat.side_effect = httpx.HTTPStatusError(
            "server error", request=request, response=httpx.Response(500, request=request)
        )

        response = client.post("/webhook/response", json=_text_update(456, "hola"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text=Constants.LLM_ERROR_MESSAGE
        )

    def test_free_text_message_replies_with_llm_error_message_when_the_model_returns_empty(
        self, client: TestClient, mock_bot: AsyncMock, mock_llm: AsyncMock
    ) -> None:
        # Telegram rechaza un sendMessage con texto vacio, asi que nunca debe intentarse.
        mock_llm.chat.return_value = "   \n  "

        response = client.post("/webhook/response", json=_text_update(456, "hola"))

        assert response.status_code == 200
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text=Constants.LLM_ERROR_MESSAGE
        )

    def test_replies_with_server_error_message_when_something_else_fails(
        self, client: TestClient, mock_bot: AsyncMock, mock_llm: AsyncMock
    ) -> None:
        mock_llm.chat.return_value = "agent reply"
        # Primer envio (la respuesta del modelo) revienta; el segundo es el aviso de error.
        mock_bot.send_message.side_effect = [RuntimeError("telegram caido"), None]

        response = client.post("/webhook/response", json=_text_update(456, "hola"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert mock_bot.send_message.await_args.kwargs == {
            "chat_id": 456,
            "text": Constants.SERVER_ERROR_MESSAGE,
        }

    def test_start_command_still_greets_when_followed_by_emoji(
        self, client: TestClient, mock_bot: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json=_text_update(123, "/start 👋"))

        assert response.status_code == 200
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=123, message_thread_id=None, text=Constants.WELCOME_MESSAGE
        )

    def test_emoji_only_message_replies_with_invalid_text(
        self, client: TestClient, mock_bot: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json=_text_update(456, "👋🔥💪"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text=Constants.INVALID_TEXT_MESSAGE
        )

    def test_whitespace_only_message_replies_with_invalid_text(
        self, client: TestClient, mock_bot: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json=_text_update(456, "   "))

        assert response.status_code == 200
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text=Constants.INVALID_TEXT_MESSAGE
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


def _webhook_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Solo los registros del webhook: caplog captura tambien los de httpx."""
    return [
        record
        for record in caplog.records
        if record.name == "fitcoach.service.conversation_service"
    ]


class TestLogTraceability:
    def test_info_logs_correlate_chat_thread_message_update_and_user(
        self, client: TestClient, mock_llm: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_llm.chat.return_value = "respuesta del agente"
        caplog.set_level(logging.INFO, logger="fitcoach.service.conversation_service")

        client.post("/webhook/response", json=_text_update(456, "hola"))

        ctx = "[update=1 chat=456 thread=None msg=10 user=desconocido]"
        records = _webhook_records(caplog)
        assert records
        assert all(record.message.startswith(ctx) for record in records)
        assert any("entrada='hola'" in record.message for record in records)

    def test_info_logs_the_model_output_and_its_latency(
        self, client: TestClient, mock_llm: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_llm.chat.return_value = "respuesta del agente"
        caplog.set_level(logging.INFO, logger="fitcoach.service.conversation_service")

        client.post("/webhook/response", json=_text_update(456, "hola"))

        reply_logs = [r for r in _webhook_records(caplog) if "respuesta del LLM" in r.message]
        assert len(reply_logs) == 1
        assert "'respuesta del agente'" in reply_logs[0].message
        assert regex.search(r"en \d+ms", reply_logs[0].message)

    def test_debug_logs_the_real_llm_payload(
        self, client: TestClient, mock_llm: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_llm.chat.return_value = "respuesta del agente"
        caplog.set_level(logging.DEBUG, logger="fitcoach.service.conversation_service")

        client.post("/webhook/response", json=_text_update(456, "hola"))

        payload_logs = [r for r in _webhook_records(caplog) if "entrada al LLM:" in r.message]
        assert len(payload_logs) == 1
        assert payload_logs[0].levelno == logging.DEBUG
        assert "system[0 chars]=''" in payload_logs[0].message
        assert "user[4 chars]='hola'" in payload_logs[0].message

    def test_emoji_only_message_is_logged_as_warning_not_error(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG, logger="fitcoach.service.conversation_service")

        client.post("/webhook/response", json=_text_update(456, "👋🔥💪"))

        records = _webhook_records(caplog)
        assert not [r for r in records if r.levelno >= logging.ERROR]
        assert [r for r in records if r.levelno == logging.WARNING]

    def test_message_without_text_logs_the_real_update_id_not_minus_one(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG, logger="fitcoach.service.conversation_service")
        update = {
            "update_id": 77,
            "message": {"message_id": 11, "date": 0, "chat": {"id": 789, "type": "private"}},
        }

        client.post("/webhook/response", json=update)

        warnings = [r for r in _webhook_records(caplog) if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "update=77" in warnings[0].message
        assert "update=-1" not in warnings[0].message

    def test_llm_failure_is_logged_as_error(
        self, client: TestClient, mock_llm: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_llm.chat.side_effect = RuntimeError("boom")
        caplog.set_level(logging.INFO, logger="fitcoach.service.conversation_service")

        client.post("/webhook/response", json=_text_update(456, "hola"))

        errors = [r for r in _webhook_records(caplog) if r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "fallo al invocar el modelo" in errors[0].message


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
            chat_id=123, message_thread_id=None, text=Constants.WELCOME_MESSAGE
        )

    def test_webhook_response_route_only_accepts_post(self) -> None:
        response = TestClient(fitcoach_app).get("/webhook/response")

        assert response.status_code == 405
