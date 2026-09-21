import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Bot, Message, Update
from telegram.error import RetryAfter

from fitcoach.domain.constants import Constants
from fitcoach.domain.conversation import ConversationMessage
from fitcoach.domain.entities import IAInput, IAMessage
from fitcoach.domain.interviewer_errors import InterviewerError, InterviewerErrorCode
from fitcoach.domain.interviewer_profile import InterviewerTurn
from fitcoach.domain.rate_limiter import UsageLimits
from fitcoach.repository.conversation_repository import ConversationRepository
from fitcoach.service import conversation_service
from fitcoach.service.agent.interviewer_chain import InterviewerChain, InterviewerReply
from fitcoach.service.conversation_service import (
    ConversationService,
    format_llm_input,
    remove_emojis,
    truncate,
    user_label,
)


@pytest.fixture
def mock_bot() -> AsyncMock:
    return AsyncMock(spec=Bot)


@pytest.fixture
def mock_interviewer() -> AsyncMock:
    return AsyncMock(spec=InterviewerChain)


# Cuota holgada: la mayoria de tests no ejercitan el limite y no deben chocar con el.
_NO_QUOTA_PRESSURE = UsageLimits(
    hard_tokens=1_000_000, soft_tokens=900_000, window=timedelta(hours=24)
)
# Cuota estrecha para los tests del propio limite: /interview corta en 900, texto libre en 1000.
_TIGHT_QUOTA = UsageLimits(hard_tokens=1_000, soft_tokens=900, window=timedelta(hours=24))


@pytest.fixture
def mock_conversation_repository() -> AsyncMock:
    repository = AsyncMock(spec=ConversationRepository)
    # Sin esto el mock devuelve otro AsyncMock y la comparacion con el umbral falla.
    repository.tokens_used_since.return_value = 0
    return repository


@pytest.fixture
def service(
    mock_bot: AsyncMock,
    mock_interviewer: AsyncMock,
    mock_conversation_repository: AsyncMock,
) -> ConversationService:
    return ConversationService(
        bot=mock_bot,
        interviewer=mock_interviewer,
        conversation_repository=mock_conversation_repository,
        usage_limits=_NO_QUOTA_PRESSURE,
    )


def _message_payload(
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> dict[str, object]:
    """Mensaje minimo; incluye `from` solo si se da algun dato del remitente."""
    payload: dict[str, object] = {
        "message_id": 1,
        "date": 0,
        "chat": {"id": 1, "type": "private"},
    }
    if username or first_name or last_name:
        sender: dict[str, object] = {"id": 7, "is_bot": False, "first_name": first_name or ""}
        if username:
            sender["username"] = username
        if last_name:
            sender["last_name"] = last_name
        payload["from"] = sender
    return payload


def _text_update(chat_id: int, text: str) -> Update:
    return Update.de_json({
        "update_id": 1,
        "message": {
            "message_id": 10,
            "date": 0,
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    })


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


class TestLogHelpers:
    def test_truncate_leaves_short_text_untouched(self) -> None:
        assert truncate("hola") == "'hola'"

    def test_truncate_marks_long_text_as_truncated_with_its_total_length(self) -> None:
        result = truncate("a" * 500)

        assert "[TRUNCADO: 500 chars en total]" in result
        assert len(result) < 500

    def test_truncate_keeps_multiline_text_on_a_single_line(self) -> None:
        # repr() escapa los saltos de linea: un registro de log = una linea.
        assert "\n" not in truncate("linea1\nlinea2")

    def test_user_label_prefers_the_username(self) -> None:
        message = Message.de_json(_message_payload(username="ImRu10X", first_name="Raul"))

        assert user_label(message) == "ImRu10X"

    def test_user_label_falls_back_to_the_full_name(self) -> None:
        message = Message.de_json(_message_payload(first_name="Raul", last_name="Soriano"))

        assert user_label(message) == "Raul Soriano"

    def test_user_label_returns_unknown_when_there_is_no_sender(self) -> None:
        message = Message.de_json(_message_payload())

        assert user_label(message) == Constants.UNKNOWN_USER

    def test_user_label_returns_unknown_when_there_is_no_message(self) -> None:
        assert user_label(None) == Constants.UNKNOWN_USER

    def test_format_llm_input_shows_role_length_and_real_content(self) -> None:
        llm_input = IAInput([
            IAMessage(role="system", message=""),
            IAMessage(message="Buenos dias"),
        ])

        formatted = format_llm_input(llm_input)

        # Guarda de regresion: antes se imprimia "<IAInput object at 0x...>".
        assert "system[0 chars]=''" in formatted
        assert "user[11 chars]='Buenos dias'" in formatted
        assert "object at" not in formatted


class TestSlowModelWarning:
    @pytest.mark.asyncio
    async def test_warns_when_the_model_takes_longer_than_the_threshold(
        self,
        service: ConversationService,
        mock_interviewer: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(Constants, "SLOW_LLM_MS", -1)  # cualquier latencia lo supera
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="respuesta"),
            token_usages=[],
        )
        caplog.set_level(logging.WARNING, logger="fitcoach.service.conversation_service")

        await service.handle_update(_text_update(456, "hola"))

        assert any("respuesta lenta del modelo" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_does_not_warn_when_the_model_responds_fast(
        self,
        service: ConversationService,
        mock_interviewer: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="respuesta"),
            token_usages=[],
        )
        caplog.set_level(logging.WARNING, logger="fitcoach.service.conversation_service")

        await service.handle_update(_text_update(456, "hola"))

        assert not [r for r in caplog.records if "respuesta lenta" in r.message]


class TestPersistentConversation:
    @pytest.mark.asyncio
    async def test_loads_recent_history_and_persists_a_successful_turn(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
    ) -> None:
        history = [
            ConversationMessage(
                chat_id=456,
                role="user",
                content="Me llamo Ana",
                created_at=datetime.now(UTC),
            )
        ]
        mock_conversation_repository.get_recent.return_value = history
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="Hola Ana"),
            token_usages=[],
        )
        service = ConversationService(
            bot=mock_bot,
            interviewer=mock_interviewer,
            conversation_repository=mock_conversation_repository,
            usage_limits=_NO_QUOTA_PRESSURE,
            history_window_messages=12,
        )

        await service.handle_update(_text_update(456, "Quiero ganar músculo"))

        mock_conversation_repository.get_recent.assert_awaited_once_with(456, 12)
        mock_interviewer.respond.assert_awaited_once_with("Quiero ganar músculo", history)
        mock_conversation_repository.add_turn.assert_awaited_once_with(
            456, "Quiero ganar músculo", "Hola Ana"
        )

    @pytest.mark.asyncio
    async def test_sends_report_and_persists_profile_when_interview_completes(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
    ) -> None:
        profile = MagicMock()
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn.model_construct(
                status="completed",
                reply="He completado tu perfil.",
                report="Resumen de tu entrevista",
                profile=profile,
            ),
            token_usages=[],
        )
        service = ConversationService(
            bot=mock_bot,
            interviewer=mock_interviewer,
            conversation_repository=mock_conversation_repository,
            usage_limits=_NO_QUOTA_PRESSURE,
        )

        await service.handle_update(_text_update(456, "Mi respuesta final"))

        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456,
            message_thread_id=None,
            text="Resumen de tu entrevista",
        )
        mock_conversation_repository.complete_interview.assert_awaited_once_with(
            456,
            "Mi respuesta final",
            "He completado tu perfil.",
            profile,
            "Resumen de tu entrevista",
        )

    @pytest.mark.asyncio
    async def test_completed_interview_offers_restart(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
    ) -> None:
        mock_conversation_repository.get_interview_status.return_value = "completed"
        service = ConversationService(
            bot=mock_bot,
            interviewer=mock_interviewer,
            conversation_repository=mock_conversation_repository,
            usage_limits=_NO_QUOTA_PRESSURE,
        )

        await service.handle_update(_text_update(456, "Quiero cambiar mi objetivo"))

        mock_interviewer.respond.assert_not_awaited()
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456,
            message_thread_id=None,
            text=Constants.INTERVIEW_COMPLETED_MESSAGE,
        )


class TestInterviewerErrorHandling:
    @pytest.mark.asyncio
    async def test_persists_failed_llm_call_without_conversation_message(
        self,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
    ) -> None:
        mock_interviewer.respond.side_effect = InterviewerError(
            InterviewerErrorCode.TIMEOUT, retryable=True
        )
        service = ConversationService(
            bot=AsyncMock(spec=Bot),
            interviewer=mock_interviewer,
            conversation_repository=mock_conversation_repository,
            usage_limits=_NO_QUOTA_PRESSURE,
        )

        await service.handle_update(_text_update(456, "Hola"))

        usage = mock_conversation_repository.record_token_usage.await_args.kwargs
        assert usage["status"] == InterviewerErrorCode.TIMEOUT.value
        assert usage["conversation_message_id"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("code", "expected_message"),
        [
            (InterviewerErrorCode.AUTHENTICATION, Constants.LLM_AUTHENTICATION_ERROR_MESSAGE),
            (InterviewerErrorCode.QUOTA, Constants.LLM_QUOTA_ERROR_MESSAGE),
            (InterviewerErrorCode.RATE_LIMITED, Constants.LLM_RATE_LIMIT_ERROR_MESSAGE),
            (InterviewerErrorCode.INVALID_REQUEST, Constants.LLM_INVALID_REQUEST_ERROR_MESSAGE),
            (InterviewerErrorCode.OUTPUT_LIMIT, Constants.LLM_OUTPUT_LIMIT_ERROR_MESSAGE),
            (InterviewerErrorCode.TIMEOUT, Constants.LLM_TIMEOUT_ERROR_MESSAGE),
            (InterviewerErrorCode.UNAVAILABLE, Constants.LLM_UNAVAILABLE_ERROR_MESSAGE),
            (InterviewerErrorCode.INVALID_OUTPUT, Constants.LLM_INVALID_OUTPUT_ERROR_MESSAGE),
        ],
    )
    async def test_sends_a_safe_message_for_each_interviewer_error(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
        code: InterviewerErrorCode,
        expected_message: str,
    ) -> None:
        mock_interviewer.respond.side_effect = InterviewerError(code, retryable=True)
        service = ConversationService(
            bot=mock_bot,
            interviewer=mock_interviewer,
            conversation_repository=mock_conversation_repository,
            usage_limits=_NO_QUOTA_PRESSURE,
        )

        await service.handle_update(_text_update(456, "Hola"))

        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456,
            message_thread_id=None,
            text=expected_message,
        )
        mock_conversation_repository.add_turn.assert_not_awaited()


class TestUnexpectedErrorHandling:
    @pytest.mark.asyncio
    async def test_does_not_try_to_notify_when_there_is_no_message_to_reply_to(
        self, service: ConversationService, mock_bot: AsyncMock
    ) -> None:
        # Sin mensaje no hay chat al que contestar: debe rendirse en silencio.
        mock_bot.send_message.side_effect = RuntimeError("telegram caido")
        update = Update.de_json({"update_id": 9})

        await service.handle_update(update)

        # Solo el intento del camino normal; no se reintenta el aviso de error.
        assert mock_bot.send_message.await_count == 1

    @pytest.mark.asyncio
    async def test_survives_when_even_the_error_notice_fails(
        self,
        service: ConversationService,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="respuesta"),
            token_usages=[],
        )
        mock_bot.send_message.side_effect = RuntimeError("telegram caido")
        caplog.set_level(logging.ERROR, logger="fitcoach.service.conversation_service")

        # No debe propagar: si lo hiciera, Telegram reintentaria el update.
        await service.handle_update(_text_update(456, "hola"))

        assert any("tampoco se pudo avisar al usuario" in r.message for r in caplog.records)


class TestTelegramFloodControl:
    @pytest.mark.asyncio
    async def test_retries_once_after_a_short_retry_after(
        self,
        service: ConversationService,
        mock_bot: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        slept: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(conversation_service.asyncio, "sleep", _fake_sleep)
        mock_bot.send_message.side_effect = [RetryAfter(2), None]

        await service.handle_update(_text_update(123, "/start"))

        assert mock_bot.send_message.await_count == 2
        assert slept == [2]

    @pytest.mark.asyncio
    async def test_gives_up_when_telegram_asks_for_a_long_wait(
        self,
        service: ConversationService,
        mock_bot: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Esperar mas bloquearia la peticion y Telegram reenviaria el update."""
        slept: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            slept.append(seconds)

        monkeypatch.setattr(conversation_service.asyncio, "sleep", _fake_sleep)
        espera = Constants.MAX_TELEGRAM_RETRY_SECONDS + 1
        mock_bot.send_message.side_effect = RetryAfter(espera)
        caplog.set_level(logging.WARNING, logger="fitcoach.service.conversation_service")

        await service.handle_update(_text_update(123, "/start"))

        assert mock_bot.send_message.await_count == 1
        assert slept == []
        assert any("se descarta el envio" in record.message for record in caplog.records)


def _quota_service(
    mock_bot: AsyncMock,
    mock_interviewer: AsyncMock,
    mock_conversation_repository: AsyncMock,
    consumed_tokens: int,
) -> ConversationService:
    """Servicio con cuota estrecha y un consumo previo dado para el chat."""
    mock_conversation_repository.tokens_used_since.return_value = consumed_tokens
    return ConversationService(
        bot=mock_bot,
        interviewer=mock_interviewer,
        conversation_repository=mock_conversation_repository,
        usage_limits=_TIGHT_QUOTA,
    )


class TestUsageQuota:
    @pytest.mark.asyncio
    async def test_lets_the_turn_through_when_consumption_is_below_the_threshold(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
    ) -> None:
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="Cuentame mas"),
            token_usages=[],
        )
        service = _quota_service(mock_bot, mock_interviewer, mock_conversation_repository, 899)

        await service.handle_update(_text_update(456, "Quiero ganar musculo"))

        mock_interviewer.respond.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_blocks_free_text_when_the_hard_threshold_is_reached(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
    ) -> None:
        service = _quota_service(mock_bot, mock_interviewer, mock_conversation_repository, 1_000)

        await service.handle_update(_text_update(456, "Quiero ganar musculo"))

        mock_interviewer.respond.assert_not_awaited()
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456,
            message_thread_id=None,
            text=Constants.QUOTA_EXCEEDED_MESSAGE,
        )

    @pytest.mark.asyncio
    async def test_blocks_a_new_interview_at_the_soft_threshold(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
    ) -> None:
        service = _quota_service(mock_bot, mock_interviewer, mock_conversation_repository, 900)

        await service.handle_update(_text_update(456, "/interview"))

        # Critico: `restart_interview` borra historial y perfil. Cortar despues de
        # llamarlo destruiria los datos del usuario y ademas le negaria el servicio.
        mock_conversation_repository.restart_interview.assert_not_awaited()
        mock_interviewer.respond.assert_not_awaited()
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456,
            message_thread_id=None,
            text=Constants.QUOTA_SOFT_MESSAGE,
        )

    @pytest.mark.asyncio
    async def test_free_text_still_works_between_both_thresholds(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
    ) -> None:
        """Degradacion escalonada: se corta lo caro y se deja terminar lo empezado."""
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="Casi terminamos"),
            token_usages=[],
        )
        service = _quota_service(mock_bot, mock_interviewer, mock_conversation_repository, 950)

        await service.handle_update(_text_update(456, "Entreno tres dias"))

        mock_interviewer.respond.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_logs_a_warning_with_the_cause_when_it_blocks(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        service = _quota_service(mock_bot, mock_interviewer, mock_conversation_repository, 1_500)
        caplog.set_level(logging.WARNING, logger="fitcoach.service.conversation_service")

        await service.handle_update(_text_update(456, "Quiero ganar musculo"))

        blocked = [r for r in caplog.records if "cuota superada" in r.message]
        assert len(blocked) == 1
        assert "consumido=1500" in blocked[0].message
        assert "limite=1000" in blocked[0].message
        assert "456" in blocked[0].message  # el chat_id llega en el contexto

    @pytest.mark.asyncio
    async def test_does_not_query_consumption_for_commands_that_never_call_the_model(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
    ) -> None:
        service = _quota_service(mock_bot, mock_interviewer, mock_conversation_repository, 99_999)

        await service.handle_update(_text_update(456, "/start"))

        mock_conversation_repository.tokens_used_since.assert_not_awaited()
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456,
            message_thread_id=None,
            text=Constants.WELCOME_MESSAGE,
        )

    @pytest.mark.asyncio
    async def test_asks_for_the_consumption_of_the_configured_window(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
    ) -> None:
        service = _quota_service(mock_bot, mock_interviewer, mock_conversation_repository, 1_000)

        await service.handle_update(_text_update(456, "Quiero ganar musculo"))

        chat_id, since = mock_conversation_repository.tokens_used_since.await_args.args
        assert chat_id == 456
        # Debe ser tz-aware: `created_at` es TIMESTAMPTZ y asyncpg no compara naive.
        assert since.tzinfo is not None
        assert abs((datetime.now(UTC) - since) - _TIGHT_QUOTA.window) < timedelta(seconds=5)
