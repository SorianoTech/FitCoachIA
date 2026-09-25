import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Bot, Message, Update

from fitcoach.domain.agent_errors import AgentError, AgentErrorCode
from fitcoach.domain.agents import AgentType
from fitcoach.domain.constants import Constants
from fitcoach.domain.conversation import ConversationMessage
from fitcoach.domain.entities import IAInput, IAMessage
from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile, InterviewerTurn
from fitcoach.domain.token_usage import TokenUsage
from fitcoach.domain.trainer_plan import TRAINING_STATUS_ACTIVE, TrainerTurn, TrainingPlan
from fitcoach.repository.conversation_repository import (
    ConversationRepository,
    StoredTrainingPlan,
)
from fitcoach.service.agent.exercise_retriever import ExerciseRetriever
from fitcoach.service.agent.interviewer_chain import InterviewerChain, InterviewerReply
from fitcoach.service.agent.trainer_chain import TrainerChain, TrainerReply
from fitcoach.service.conversation_service import (
    ConversationService,
    format_llm_input,
    remove_emojis,
    truncate,
    user_label,
)
from tests.unit_test.conftest import build_plan_payload


@pytest.fixture
def mock_bot() -> AsyncMock:
    return AsyncMock(spec=Bot)


@pytest.fixture
def mock_interviewer() -> AsyncMock:
    return AsyncMock(spec=InterviewerChain)


@pytest.fixture
def mock_conversation_repository() -> AsyncMock:
    return AsyncMock(spec=ConversationRepository)


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
        )

        await service.handle_update(_text_update(456, "Quiero cambiar mi objetivo"))

        mock_interviewer.respond.assert_not_awaited()
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456,
            message_thread_id=None,
            text=Constants.INTERVIEW_COMPLETED_MESSAGE,
        )


class TestAgentErrorHandling:
    @pytest.mark.asyncio
    async def test_persists_failed_llm_call_without_conversation_message(
        self,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
    ) -> None:
        mock_interviewer.respond.side_effect = AgentError(AgentErrorCode.TIMEOUT, retryable=True)
        service = ConversationService(
            bot=AsyncMock(spec=Bot),
            interviewer=mock_interviewer,
            conversation_repository=mock_conversation_repository,
        )

        await service.handle_update(_text_update(456, "Hola"))

        usage = mock_conversation_repository.record_token_usage.await_args.kwargs
        assert usage["status"] == AgentErrorCode.TIMEOUT.value
        assert usage["conversation_message_id"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("code", "expected_message"),
        [
            (AgentErrorCode.AUTHENTICATION, Constants.LLM_AUTHENTICATION_ERROR_MESSAGE),
            (AgentErrorCode.QUOTA, Constants.LLM_QUOTA_ERROR_MESSAGE),
            (AgentErrorCode.RATE_LIMITED, Constants.LLM_RATE_LIMIT_ERROR_MESSAGE),
            (AgentErrorCode.INVALID_REQUEST, Constants.LLM_INVALID_REQUEST_ERROR_MESSAGE),
            (AgentErrorCode.OUTPUT_LIMIT, Constants.LLM_OUTPUT_LIMIT_ERROR_MESSAGE),
            (AgentErrorCode.TIMEOUT, Constants.LLM_TIMEOUT_ERROR_MESSAGE),
            (AgentErrorCode.UNAVAILABLE, Constants.LLM_UNAVAILABLE_ERROR_MESSAGE),
            (AgentErrorCode.INVALID_OUTPUT, Constants.LLM_INVALID_OUTPUT_ERROR_MESSAGE),
        ],
    )
    async def test_sends_a_safe_message_for_each_interviewer_error(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
        code: AgentErrorCode,
        expected_message: str,
    ) -> None:
        mock_interviewer.respond.side_effect = AgentError(code, retryable=True)
        service = ConversationService(
            bot=mock_bot,
            interviewer=mock_interviewer,
            conversation_repository=mock_conversation_repository,
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


class TestTrainerFlow:
    """`/train` y las preguntas posteriores sobre el plan."""

    @pytest.fixture
    def mock_trainer(self) -> AsyncMock:
        return AsyncMock(spec=TrainerChain)

    @pytest.fixture
    def mock_retriever(self, exercises: list[Exercise]) -> AsyncMock:
        retriever = AsyncMock(spec=ExerciseRetriever)
        retriever.retrieve.return_value = exercises
        return retriever

    @pytest.fixture
    def trainer_service(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
        mock_trainer: AsyncMock,
        mock_retriever: AsyncMock,
    ) -> ConversationService:
        return ConversationService(
            bot=mock_bot,
            interviewer=mock_interviewer,
            conversation_repository=mock_conversation_repository,
            trainer=mock_trainer,
            exercise_retriever=mock_retriever,
        )

    @staticmethod
    def _plan_reply() -> TrainerReply:
        return TrainerReply(
            turn=TrainerTurn(
                status="plan",
                reply="Listo",
                report="Tu plan de 4 semanas",
                plan=TrainingPlan.model_validate(build_plan_payload()),
            ),
            token_usages=[],
        )

    @staticmethod
    def _sent_texts(mock_bot: AsyncMock) -> list[str]:
        return [call.kwargs["text"] for call in mock_bot.send_message.await_args_list]

    @pytest.mark.asyncio
    async def test_train_without_a_profile_asks_for_the_interview_first(
        self,
        trainer_service: ConversationService,
        mock_bot: AsyncMock,
        mock_conversation_repository: AsyncMock,
        mock_trainer: AsyncMock,
    ) -> None:
        mock_conversation_repository.get_interviewer_profile.return_value = None

        await trainer_service.handle_update(_text_update(456, "/train"))

        assert Constants.NO_PROFILE_MESSAGE in self._sent_texts(mock_bot)
        mock_trainer.generate_plan.assert_not_awaited()
        mock_conversation_repository.save_training_plan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_train_generates_sends_and_persists_the_plan(
        self,
        trainer_service: ConversationService,
        mock_bot: AsyncMock,
        mock_conversation_repository: AsyncMock,
        mock_trainer: AsyncMock,
        profile: InterviewerProfile,
        exercises: list[Exercise],
    ) -> None:
        mock_conversation_repository.get_interviewer_profile.return_value = profile
        mock_trainer.generate_plan.return_value = self._plan_reply()

        await trainer_service.handle_update(_text_update(456, "/train"))

        texts = self._sent_texts(mock_bot)
        assert Constants.PLAN_GENERATING_MESSAGE in texts
        assert "Tu plan de 4 semanas" in texts
        mock_trainer.generate_plan.assert_awaited_once_with(profile, exercises)
        mock_conversation_repository.save_training_plan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_train_refuses_when_the_catalogue_cannot_be_reached(
        self,
        trainer_service: ConversationService,
        mock_bot: AsyncMock,
        mock_conversation_repository: AsyncMock,
        mock_retriever: AsyncMock,
        mock_trainer: AsyncMock,
        profile: InterviewerProfile,
    ) -> None:
        # Un mesociclo sin catalogo es justo lo que este agente existe para evitar.
        mock_conversation_repository.get_interviewer_profile.return_value = profile
        mock_retriever.retrieve.side_effect = AgentError(AgentErrorCode.UNAVAILABLE, retryable=True)

        await trainer_service.handle_update(_text_update(456, "/train"))

        assert Constants.TRAINER_UNAVAILABLE_MESSAGE in self._sent_texts(mock_bot)
        mock_trainer.generate_plan.assert_not_awaited()
        mock_conversation_repository.save_training_plan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_train_refuses_when_the_catalogue_is_empty(
        self,
        trainer_service: ConversationService,
        mock_bot: AsyncMock,
        mock_conversation_repository: AsyncMock,
        mock_retriever: AsyncMock,
        mock_trainer: AsyncMock,
        profile: InterviewerProfile,
    ) -> None:
        mock_conversation_repository.get_interviewer_profile.return_value = profile
        mock_retriever.retrieve.return_value = []

        await trainer_service.handle_update(_text_update(456, "/train"))

        assert Constants.TRAINER_UNAVAILABLE_MESSAGE in self._sent_texts(mock_bot)
        mock_trainer.generate_plan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_train_records_token_usage_under_the_trainer_agent(
        self,
        trainer_service: ConversationService,
        mock_conversation_repository: AsyncMock,
        mock_trainer: AsyncMock,
        profile: InterviewerProfile,
    ) -> None:
        mock_conversation_repository.get_interviewer_profile.return_value = profile
        mock_conversation_repository.save_training_plan.return_value = 77
        mock_trainer.generate_plan.return_value = TrainerReply(
            turn=self._plan_reply().turn,
            token_usages=[
                TokenUsage(
                    model="gpt-test",
                    prompt_tokens=900,
                    completion_tokens=700,
                    total_tokens=1600,
                )
            ],
        )

        await trainer_service.handle_update(_text_update(456, "/train"))

        call = mock_conversation_repository.record_token_usage.await_args
        assert call.kwargs["agent"] == AgentType.TRAINER.value
        assert call.kwargs["total_tokens"] == 1600
        assert call.kwargs["conversation_message_id"] == 77

    @pytest.mark.asyncio
    async def test_train_relays_an_answer_turn_without_persisting_a_plan(
        self,
        trainer_service: ConversationService,
        mock_bot: AsyncMock,
        mock_conversation_repository: AsyncMock,
        mock_trainer: AsyncMock,
        profile: InterviewerProfile,
    ) -> None:
        mock_conversation_repository.get_interviewer_profile.return_value = profile
        mock_trainer.generate_plan.return_value = TrainerReply(
            turn=TrainerTurn(status="answer", reply="No puedo con este catalogo"),
            token_usages=[],
        )

        await trainer_service.handle_update(_text_update(456, "/train"))

        assert "No puedo con este catalogo" in self._sent_texts(mock_bot)
        mock_conversation_repository.save_training_plan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_train_sends_a_safe_message_when_the_model_fails(
        self,
        trainer_service: ConversationService,
        mock_bot: AsyncMock,
        mock_conversation_repository: AsyncMock,
        mock_trainer: AsyncMock,
        profile: InterviewerProfile,
    ) -> None:
        mock_conversation_repository.get_interviewer_profile.return_value = profile
        mock_trainer.generate_plan.side_effect = AgentError(
            AgentErrorCode.RATE_LIMITED, retryable=True
        )

        await trainer_service.handle_update(_text_update(456, "/train"))

        assert Constants.LLM_RATE_LIMIT_ERROR_MESSAGE in self._sent_texts(mock_bot)
        mock_conversation_repository.save_training_plan.assert_not_awaited()
        assert (
            mock_conversation_repository.record_token_usage.await_args.kwargs["agent"]
            == AgentType.TRAINER.value
        )

    @pytest.mark.asyncio
    async def test_train_reports_unavailable_when_no_trainer_is_configured(
        self,
        service: ConversationService,
        mock_bot: AsyncMock,
        mock_conversation_repository: AsyncMock,
    ) -> None:
        # El servicio sin entrenador (despliegue sin BD vectorial) no debe romper.
        await service.handle_update(_text_update(456, "/train"))

        assert Constants.TRAINER_UNAVAILABLE_MESSAGE in self._sent_texts(mock_bot)
        mock_conversation_repository.get_interviewer_profile.assert_not_awaited()


class TestFreeMessageRouting:
    """Tabla de enrutado: que agente atiende un mensaje sin comando."""

    @pytest.fixture
    def mock_trainer(self) -> AsyncMock:
        return AsyncMock(spec=TrainerChain)

    @pytest.fixture
    def routed_service(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
        mock_trainer: AsyncMock,
        exercises: list[Exercise],
    ) -> ConversationService:
        retriever = AsyncMock(spec=ExerciseRetriever)
        retriever.retrieve.return_value = exercises
        return ConversationService(
            bot=mock_bot,
            interviewer=mock_interviewer,
            conversation_repository=mock_conversation_repository,
            trainer=mock_trainer,
            exercise_retriever=retriever,
        )

    @staticmethod
    def _stored_plan() -> StoredTrainingPlan:
        return StoredTrainingPlan(
            id=1,
            version=1,
            plan=TrainingPlan.model_validate(build_plan_payload()),
            report="informe",
        )

    @pytest.mark.asyncio
    async def test_interview_completed_without_a_plan_points_at_train(
        self,
        routed_service: ConversationService,
        mock_bot: AsyncMock,
        mock_conversation_repository: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_trainer: AsyncMock,
    ) -> None:
        mock_conversation_repository.get_interview_status.return_value = "completed"
        mock_conversation_repository.get_training_status.return_value = None

        await routed_service.handle_update(_text_update(456, "hola"))

        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456,
            message_thread_id=None,
            text=Constants.INTERVIEW_COMPLETED_MESSAGE,
        )
        mock_interviewer.respond.assert_not_awaited()
        mock_trainer.answer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_active_plan_routes_the_message_to_the_trainer(
        self,
        routed_service: ConversationService,
        mock_bot: AsyncMock,
        mock_conversation_repository: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_trainer: AsyncMock,
        profile: InterviewerProfile,
    ) -> None:
        mock_conversation_repository.get_interview_status.return_value = "completed"
        mock_conversation_repository.get_training_status.return_value = TRAINING_STATUS_ACTIVE
        mock_conversation_repository.get_current_plan.return_value = self._stored_plan()
        mock_conversation_repository.get_interviewer_profile.return_value = profile
        mock_conversation_repository.get_recent.return_value = []
        mock_trainer.answer.return_value = TrainerReply(
            turn=TrainerTurn(status="answer", reply="Porque progresas mejor"),
            token_usages=[],
        )

        await routed_service.handle_update(_text_update(456, "por que 3 dias?"))

        mock_trainer.answer.assert_awaited_once()
        mock_interviewer.respond.assert_not_awaited()
        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text="Porque progresas mejor"
        )
        # El historial que se pide es el del entrenador, no el de la entrevista.
        assert mock_conversation_repository.get_recent.await_args.args[2] == AgentType.TRAINER.value

    @pytest.mark.asyncio
    async def test_the_trainer_turn_is_persisted_under_the_trainer_agent(
        self,
        routed_service: ConversationService,
        mock_conversation_repository: AsyncMock,
        mock_trainer: AsyncMock,
        profile: InterviewerProfile,
    ) -> None:
        mock_conversation_repository.get_interview_status.return_value = "completed"
        mock_conversation_repository.get_training_status.return_value = TRAINING_STATUS_ACTIVE
        mock_conversation_repository.get_current_plan.return_value = self._stored_plan()
        mock_conversation_repository.get_interviewer_profile.return_value = profile
        mock_conversation_repository.get_recent.return_value = []
        mock_trainer.answer.return_value = TrainerReply(
            turn=TrainerTurn(status="answer", reply="Claro"), token_usages=[]
        )

        await routed_service.handle_update(_text_update(456, "duda"))

        assert mock_conversation_repository.add_turn.await_args.args[3] == AgentType.TRAINER.value

    @pytest.mark.asyncio
    async def test_answers_degrade_to_an_empty_catalogue_instead_of_refusing(
        self,
        mock_bot: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_conversation_repository: AsyncMock,
        mock_trainer: AsyncMock,
        profile: InterviewerProfile,
    ) -> None:
        # A diferencia de /train, una pregunta se puede responder desde el plan.
        retriever = AsyncMock(spec=ExerciseRetriever)
        retriever.retrieve.side_effect = AgentError(AgentErrorCode.UNAVAILABLE, retryable=True)
        service = ConversationService(
            bot=mock_bot,
            interviewer=mock_interviewer,
            conversation_repository=mock_conversation_repository,
            trainer=mock_trainer,
            exercise_retriever=retriever,
        )
        mock_conversation_repository.get_interview_status.return_value = "completed"
        mock_conversation_repository.get_training_status.return_value = TRAINING_STATUS_ACTIVE
        mock_conversation_repository.get_current_plan.return_value = (
            TestFreeMessageRouting._stored_plan()
        )
        mock_conversation_repository.get_interviewer_profile.return_value = profile
        mock_conversation_repository.get_recent.return_value = []
        mock_trainer.answer.return_value = TrainerReply(
            turn=TrainerTurn(status="answer", reply="Te respondo igualmente"), token_usages=[]
        )

        await service.handle_update(_text_update(456, "duda"))

        mock_trainer.answer.assert_awaited_once()
        assert mock_trainer.answer.await_args.args[3] == []

    @pytest.mark.asyncio
    async def test_an_active_session_without_a_stored_plan_asks_for_train(
        self,
        routed_service: ConversationService,
        mock_bot: AsyncMock,
        mock_conversation_repository: AsyncMock,
        mock_trainer: AsyncMock,
    ) -> None:
        mock_conversation_repository.get_interview_status.return_value = "completed"
        mock_conversation_repository.get_training_status.return_value = TRAINING_STATUS_ACTIVE
        mock_conversation_repository.get_current_plan.return_value = None

        await routed_service.handle_update(_text_update(456, "duda"))

        mock_bot.send_message.assert_awaited_once_with(
            chat_id=456, message_thread_id=None, text=Constants.NO_PLAN_MESSAGE
        )
        mock_trainer.answer.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_in_progress_interview_still_goes_to_the_interviewer(
        self,
        routed_service: ConversationService,
        mock_conversation_repository: AsyncMock,
        mock_interviewer: AsyncMock,
        mock_trainer: AsyncMock,
    ) -> None:
        mock_conversation_repository.get_interview_status.return_value = "in_progress"
        mock_interviewer.respond.return_value = InterviewerReply(
            turn=InterviewerTurn(status="in_progress", reply="Cuantos anos tienes?"),
            token_usages=[],
        )

        await routed_service.handle_update(_text_update(456, "hola"))

        mock_interviewer.respond.assert_awaited_once()
        mock_trainer.answer.assert_not_awaited()
