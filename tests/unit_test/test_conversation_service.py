import logging
from unittest.mock import AsyncMock

import pytest
from telegram import Bot, Message, Update

from fitcoach.domain.constants import Constants
from fitcoach.domain.entities import IAInput, IAMessage
from fitcoach.service.conversation_service import (
    ConversationService,
    format_llm_input,
    remove_emojis,
    truncate,
    user_label,
)
from fitcoach.service.llm.llm_caller import LLM


@pytest.fixture
def mock_bot() -> AsyncMock:
    return AsyncMock(spec=Bot)


@pytest.fixture
def mock_llm() -> AsyncMock:
    return AsyncMock(spec=LLM)


@pytest.fixture
def service(mock_bot: AsyncMock, mock_llm: AsyncMock) -> ConversationService:
    return ConversationService(bot=mock_bot, llm=mock_llm)


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
        mock_llm: AsyncMock,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(Constants, "SLOW_LLM_MS", -1)  # cualquier latencia lo supera
        mock_llm.chat.return_value = "respuesta"
        caplog.set_level(logging.WARNING, logger="fitcoach.service.conversation_service")

        await service.handle_update(_text_update(456, "hola"))

        assert any("respuesta lenta del modelo" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_does_not_warn_when_the_model_responds_fast(
        self,
        service: ConversationService,
        mock_llm: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_llm.chat.return_value = "respuesta"
        caplog.set_level(logging.WARNING, logger="fitcoach.service.conversation_service")

        await service.handle_update(_text_update(456, "hola"))

        assert not [r for r in caplog.records if "respuesta lenta" in r.message]


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
        mock_llm: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_llm.chat.return_value = "respuesta"
        mock_bot.send_message.side_effect = RuntimeError("telegram caido")
        caplog.set_level(logging.ERROR, logger="fitcoach.service.conversation_service")

        # No debe propagar: si lo hiciera, Telegram reintentaria el update.
        await service.handle_update(_text_update(456, "hola"))

        assert any("tampoco se pudo avisar al usuario" in r.message for r in caplog.records)
