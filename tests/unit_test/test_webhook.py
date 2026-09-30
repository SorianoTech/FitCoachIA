import logging
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
import regex
from fastapi import FastAPI
from fastapi.testclient import TestClient
from telegram import Bot

from fitcoach.api.security import verify_telegram_secret
from fitcoach.api.webhook import get_conversation_service, webhook
from fitcoach.domain.constants import Constants
from fitcoach.domain.interviewer_profile import InterviewerTurn
from fitcoach.domain.rate_limiter import UsageLimits
from fitcoach.infrastructure.bot.telegram_bot import get_bot
from fitcoach.infrastructure.config.settings import Settings, get_settings
from fitcoach.main import app as fitcoach_app
from fitcoach.repository.conversation_repository import ConversationRepository
from fitcoach.service.agent.interviewer_chain import InterviewerChain, InterviewerReply
from fitcoach.service.conversation_service import ConversationService

# Cuota holgada: estos tests verifican el endpoint, no el limite de consumo.
_NO_QUOTA_PRESSURE = UsageLimits(
    hard_tokens=1_000_000, soft_tokens=900_000, window=timedelta(hours=24)
)


def _test_settings() -> Settings:
    """Configuracion completa y hermetica: `_env_file=None` ignora el .env del disco."""
    return Settings(
        _env_file=None,
        app_env="test",
        bot_telegram_token="test-token",  # noqa: S106
        bot_telegram_url="http://test-telegram:9999",
        bot_telegram_commands=["start:Inicia FitCoach"],
        bot_telegram_secret_token="test-secret-token",  # noqa: S106
        bot_telegram_webhook_base_url="https://example.com",
    )


@pytest.fixture
def mock_bot() -> AsyncMock:
    return AsyncMock(spec=Bot)


@pytest.fixture
def mock_interviewer() -> AsyncMock:
    return AsyncMock(spec=InterviewerChain)


@pytest.fixture
def mock_conversation_repository() -> AsyncMock:
    repository = AsyncMock(spec=ConversationRepository)
    # Sin esto el mock devuelve otro AsyncMock y la comparacion con el umbral falla.
    repository.tokens_used_since.return_value = 0
    return repository


@pytest.fixture
def client(
    mock_bot: AsyncMock,
    mock_interviewer: AsyncMock,
    mock_conversation_repository: AsyncMock,
) -> TestClient:
    app = FastAPI()
    app.include_router(webhook)
    app.dependency_overrides[verify_telegram_secret] = lambda: None
    app.dependency_overrides[get_conversation_service] = lambda: ConversationService(
        bot=mock_bot,
        interviewer=mock_interviewer,
        conversation_repository=mock_conversation_repository,
        usage_limits=_NO_QUOTA_PRESSURE,
    )
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
        self, client: TestClient, mock_bot: AsyncMock, mock_interviewer: AsyncMock
    ) -> None:
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="agent reply"),
            token_usages=[],
        )

        response = client.post("/webhook/response", json=_text_update(456, "hola"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_interviewer.respond.assert_awaited_once()
        assert mock_interviewer.respond.await_args.args[0] == "hola"
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text="agent reply"
        )

    def test_free_text_emojis_are_removed_before_reaching_the_agent(
        self, client: TestClient, mock_bot: AsyncMock, mock_interviewer: AsyncMock
    ) -> None:
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="agent reply"),
            token_usages=[],
        )

        response = client.post("/webhook/response", json=_text_update(456, "hola 👋 mundo 🔥"))

        assert response.status_code == 200
        assert mock_interviewer.respond.await_args.args[0] == "hola mundo"
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text="agent reply"
        )

    def test_interview_command_starts_the_agent_conversation(
        self, client: TestClient, mock_bot: AsyncMock, mock_interviewer: AsyncMock
    ) -> None:
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="¡Bienvenido a la entrevista!"),
            token_usages=[],
        )

        response = client.post("/webhook/response", json=_text_update(456, "/interview"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_interviewer.respond.assert_awaited_once()
        assert mock_interviewer.respond.await_args.args[0] == Constants.INTERVIEW_SEED_MESSAGE
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text="¡Bienvenido a la entrevista!"
        )

    def test_interview_command_replies_with_llm_error_message_when_the_model_fails(
        self, client: TestClient, mock_bot: AsyncMock, mock_interviewer: AsyncMock
    ) -> None:
        mock_interviewer.respond.side_effect = RuntimeError("server error")

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
        self, client: TestClient, mock_bot: AsyncMock, mock_interviewer: AsyncMock
    ) -> None:
        mock_interviewer.respond.side_effect = RuntimeError("server error")

        response = client.post("/webhook/response", json=_text_update(456, "hola"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text=Constants.LLM_ERROR_MESSAGE
        )

    def test_free_text_message_replies_with_llm_error_message_when_the_model_returns_empty(
        self, client: TestClient, mock_bot: AsyncMock, mock_interviewer: AsyncMock
    ) -> None:
        # Telegram rechaza un sendMessage con texto vacio, asi que nunca debe intentarse.
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="   \n  "),
            token_usages=[],
        )

        response = client.post("/webhook/response", json=_text_update(456, "hola"))

        assert response.status_code == 200
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text=Constants.LLM_ERROR_MESSAGE
        )

    def test_replies_with_server_error_message_when_something_else_fails(
        self, client: TestClient, mock_bot: AsyncMock, mock_interviewer: AsyncMock
    ) -> None:
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="agent reply"),
            token_usages=[],
        )
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
        self, client: TestClient, mock_bot: AsyncMock, mock_interviewer: AsyncMock
    ) -> None:
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="agent reply"),
            token_usages=[],
        )

        response = client.post("/webhook/response", json=_edited_text_update(456, "hola editada"))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_interviewer.respond.assert_awaited_once()
        assert mock_interviewer.respond.await_args.args[0] == "hola editada"
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text="agent reply"
        )

    def test_edited_message_without_text_replies_with_fallback_text(
        self, client: TestClient, mock_bot: AsyncMock, mock_interviewer: AsyncMock
    ) -> None:
        response = client.post("/webhook/response", json=_edited_text_update(789))

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_interviewer.respond.assert_not_awaited()
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
        self, client: TestClient, mock_interviewer: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="respuesta del agente"),
            token_usages=[],
        )
        caplog.set_level(logging.INFO, logger="fitcoach.service.conversation_service")

        client.post("/webhook/response", json=_text_update(456, "hola"))

        ctx = "[update=1 chat=456 thread=None msg=10 user=desconocido telegram_user_id=-1]"
        records = _webhook_records(caplog)
        assert records
        assert all(record.message.startswith(ctx) for record in records)
        assert any("entrada='hola'" in record.message for record in records)

    def test_info_logs_the_model_output_and_its_latency(
        self, client: TestClient, mock_interviewer: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="respuesta del agente"),
            token_usages=[],
        )
        caplog.set_level(logging.INFO, logger="fitcoach.service.conversation_service")

        client.post("/webhook/response", json=_text_update(456, "hola"))

        reply_logs = [r for r in _webhook_records(caplog) if "respuesta del LLM" in r.message]
        assert len(reply_logs) == 1
        assert "'respuesta del agente'" in reply_logs[0].message
        assert regex.search(r"en \d+ms", reply_logs[0].message)

    def test_debug_logs_the_composed_interviewer_prompt(
        self, client: TestClient, mock_interviewer: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="respuesta del agente"),
            token_usages=[],
        )
        caplog.set_level(logging.DEBUG, logger="fitcoach.service.conversation_service")

        client.post("/webhook/response", json=_text_update(456, "hola"))

        payload_logs = [r for r in _webhook_records(caplog) if "entrada al LLM:" in r.message]
        assert len(payload_logs) == 1
        assert payload_logs[0].levelno == logging.DEBUG
        assert "system[" in payload_logs[0].message
        assert 'Interviewer ("Secretario")' in payload_logs[0].message
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
        self, client: TestClient, mock_interviewer: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_interviewer.respond.side_effect = RuntimeError("boom")
        caplog.set_level(logging.INFO, logger="fitcoach.service.conversation_service")

        client.post("/webhook/response", json=_text_update(456, "hola"))

        errors = [r for r in _webhook_records(caplog) if r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "fallo al invocar el modelo" in errors[0].message


class TestWebhookRouteRegistration:
    def test_webhook_response_route_rejects_requests_without_the_secret(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
    ) -> None:
        """Sobre la app real y SIN anular la dependencia: el candado esta puesto.

        El resto de tests del fichero anulan `verify_telegram_secret`, asi que sin
        esta comprobacion quitar la dependencia del endpoint no rompería nada.
        """
        # `verify_telegram_secret` resuelve `get_settings` de verdad: se anula para que
        # el test no dependa de que exista un .env en la maquina que lo ejecuta.
        fitcoach_app.dependency_overrides[get_settings] = _test_settings
        fitcoach_app.dependency_overrides[get_bot] = lambda: mock_bot
        fitcoach_app.dependency_overrides[get_conversation_service] = lambda: ConversationService(
            bot=mock_bot,
            interviewer=mock_interviewer,
            conversation_repository=mock_conversation_repository,
            usage_limits=_NO_QUOTA_PRESSURE,
        )
        try:
            response = TestClient(fitcoach_app).post(
                "/webhook/response", json=_text_update(123, "/start")
            )
        finally:
            fitcoach_app.dependency_overrides.pop(get_settings, None)
            fitcoach_app.dependency_overrides.pop(get_bot, None)
            fitcoach_app.dependency_overrides.pop(get_conversation_service, None)

        assert response.status_code == 403
        mock_bot.send_message.assert_not_awaited()

    def test_webhook_response_route_is_registered_on_the_app(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
    ) -> None:
        fitcoach_app.dependency_overrides[verify_telegram_secret] = lambda: None
        fitcoach_app.dependency_overrides[get_bot] = lambda: mock_bot
        fitcoach_app.dependency_overrides[get_conversation_service] = lambda: ConversationService(
            bot=mock_bot,
            interviewer=mock_interviewer,
            conversation_repository=mock_conversation_repository,
            usage_limits=_NO_QUOTA_PRESSURE,
        )
        try:
            response = TestClient(fitcoach_app).post(
                "/webhook/response", json=_text_update(123, "/start")
            )
        finally:
            fitcoach_app.dependency_overrides.pop(verify_telegram_secret, None)
            fitcoach_app.dependency_overrides.pop(get_bot, None)
            fitcoach_app.dependency_overrides.pop(get_conversation_service, None)

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=123, message_thread_id=None, text=Constants.WELCOME_MESSAGE
        )

    def test_webhook_response_route_only_accepts_post(self) -> None:
        response = TestClient(fitcoach_app).get("/webhook/response")

        assert response.status_code == 405
