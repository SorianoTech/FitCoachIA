"""Logica de conversacion: decide que responder a cada update de Telegram.

La capa de API solo traduce HTTP; toda la decision de negocio (que comando se
ha pedido, que se manda al modelo y que se le contesta al usuario) vive aqui.
"""

import logging
import time

from opentelemetry import trace
from opentelemetry.trace import Span
from telegram import Bot, Message, Update

from fitcoach.domain.agent_errors import AgentError, AgentErrorCode
from fitcoach.domain.agents import AgentType
from fitcoach.domain.constants import Constants
from fitcoach.domain.entities import IAInput, IAMessage
from fitcoach.domain.telegram import Commands
from fitcoach.domain.token_usage import TokenUsage
from fitcoach.domain.trainer_plan import TRAINING_STATUS_ACTIVE, TrainerAction
from fitcoach.infrastructure.observability.telemetry import get_tracer
from fitcoach.repository.conversation_repository import ConversationRepository
from fitcoach.service.agent import agent_factory
from fitcoach.service.agent.exercise_retriever import ExerciseRetriever
from fitcoach.service.agent.interviewer_chain import InterviewerChain, InterviewerReply
from fitcoach.service.agent.trainer_chain import TrainerChain

logger = logging.getLogger(__name__)
_tracer = get_tracer(__name__)


def remove_emojis(text: str) -> str:
    """Strip emoji, keeping letters, digits, punctuation and ordinary symbols.

    Whitespace is collapsed but not rebalanced around the removal, so a padded
    emoji leaves its separator behind: "¡Hola 👋, x" -> "¡Hola , x".
    """
    without_emojis = Constants.EMOJI_PATTERN.sub("", text)
    return Constants.WHITESPACE_PATTERN.sub(" ", without_emojis).strip()


def truncate(text: str) -> str:
    """Repr en una sola linea; marca explicitamente si se ha recortado."""
    if len(text) <= Constants.MAX_LOGGED_CHARS:
        return repr(text)
    return f"{text[: Constants.MAX_LOGGED_CHARS]!r}... [TRUNCADO: {len(text)} chars en total]"


def user_label(message: Message | None) -> str:
    """Nombre del usuario para trazas; ``from_user`` es None en channel posts."""
    user = message.from_user if message is not None else None
    if user is None:
        return Constants.UNKNOWN_USER
    return user.username or user.full_name or str(user.id)


def telegram_user_id(message: Message | None) -> int:
    """Id numerico de Telegram del remitente; distinto de ``chat_id`` en grupos/foros."""
    user = message.from_user if message is not None else None
    return user.id if user is not None else Constants.UNKNOWN_ID


def format_llm_input(llm_input: IAInput) -> str:
    """Contenido real de cada mensaje enviado al modelo, con su longitud."""
    return " | ".join(
        f"{item['role']}[{len(item['content'])} chars]={truncate(item['content'])}"
        for item in llm_input.get_input()
    )


class ConversationService:
    """Orquesta un turno de conversacion: update de Telegram -> respuesta al usuario.

    Recibe sus colaboradores por constructor para poder sustituirlos en tests
    sin levantar ni Telegram ni el modelo.
    """

    def __init__(
        self,
        bot: Bot,
        interviewer: InterviewerChain,
        conversation_repository: ConversationRepository,
        history_window_messages: int = 20,
        trainer: TrainerChain | None = None,
        exercise_retriever: ExerciseRetriever | None = None,
        trainer_history_window_messages: int = 10,
    ) -> None:
        self._bot = bot
        self._interviewer = interviewer
        self._conversation_repository = conversation_repository
        self._history_window_messages = history_window_messages
        # Optional so existing tests and any deployment without the vector
        # database keep working: /train then reports the trainer is unavailable
        # instead of crashing the webhook.
        self._trainer = trainer
        self._exercise_retriever = exercise_retriever
        self._trainer_history_window_messages = trainer_history_window_messages

    async def handle_update(self, update: Update) -> None:
        """Procesa un update y contesta al usuario. Nunca propaga excepciones.

        Telegram reenvia cualquier update que no reciba un 2xx, asi que un fallo
        no controlado aqui se convertiria en un bucle de reintentos.
        """
        message: Message | None = update.effective_message
        ctx = self._build_context(update, message)
        try:
            await self._process(update, message, ctx)
        except Exception:
            logger.exception(f"{ctx} error inesperado procesando el update")
            await self._notify_server_error(message, ctx)

    async def _process(self, update: Update, message: Message | None, ctx: str) -> None:
        edited = " (editado)" if update.edited_message is not None else ""
        logger.info(f"{ctx} update recibido{edited}")

        if message is None or not message.text:
            logger.warning(f"{ctx} update ignorado: no contiene texto")
            chat_id = message.chat_id if message is not None else Constants.UNKNOWN_ID
            await self._bot.send_message(chat_id=chat_id, text=Constants.NO_CONTENT_MESSAGE)
            return

        chat_id = message.chat_id
        message_thread_id = message.message_thread_id

        input_text = remove_emojis(message.text)
        if not input_text:
            # Nothing but emojis/whitespace survived the cleanup.
            logger.warning(f"{ctx} mensaje descartado: solo contenia emojis o espacios")
            await self._send(chat_id, message_thread_id, Constants.INVALID_TEXT_MESSAGE)
            return

        command = Commands.from_value(input_text.split(maxsplit=1)[0])
        logger.info(f"{ctx} comando={command} entrada={input_text!r}")

        with _tracer.start_as_current_span("conversation.turn") as span:
            span.set_attribute("telegram_user_id", telegram_user_id(message))
            span.set_attribute("chat_id", chat_id)
            span.set_attribute("command", command.name if command is not None else "none")

            match command:
                case Commands.START:
                    await self._send(chat_id, message_thread_id, Constants.WELCOME_MESSAGE)
                case Commands.INTERVIEW:
                    span.set_attribute("agent", AgentType.INTERVIEWER.value)
                    await self._conversation_repository.restart_interview(chat_id)
                    await self._call_interviewer(
                        ctx, chat_id, message_thread_id, Constants.INTERVIEW_SEED_MESSAGE
                    )
                case Commands.TRAIN:
                    span.set_attribute("agent", AgentType.TRAINER.value)
                    await self._generate_plan(ctx, chat_id, message_thread_id, input_text)
                case Commands.DOUBTS | Commands.PROGRESS:
                    # TODO: route to the doubts/Q&A and progress-tracking flows
                    logger.info(f"{ctx} opcion todavia no implementada")
                    await self._send(chat_id, message_thread_id, Constants.NOT_IMPLEMENTED_MESSAGE)
                case None:
                    await self._route_free_message(
                        ctx, chat_id, message_thread_id, input_text, span
                    )

    async def _route_free_message(
        self,
        ctx: str,
        chat_id: int,
        message_thread_id: int | None,
        input_text: str,
        span: Span,
    ) -> None:
        """Decide which agent owns a message that carries no command.

        | entrevista   | entrenamiento | destino                         |
        |--------------|---------------|---------------------------------|
        | null         | -             | arranca entrevista              |
        | in_progress  | -             | interviewer                     |
        | completed    | null          | "usa /train"                    |
        | completed    | active        | trainer, modo preguntas         |
        """
        status = await self._conversation_repository.get_interview_status(chat_id)
        if status == "completed":
            training_status = await self._conversation_repository.get_training_status(chat_id)
            if training_status == TRAINING_STATUS_ACTIVE:
                span.set_attribute("agent", AgentType.TRAINER.value)
                await self._answer_about_plan(ctx, chat_id, message_thread_id, input_text)
                return
            await self._send(chat_id, message_thread_id, Constants.INTERVIEW_COMPLETED_MESSAGE)
            return
        if status is None:
            await self._conversation_repository.restart_interview(chat_id)
        span.set_attribute("agent", AgentType.INTERVIEWER.value)
        await self._call_interviewer(ctx, chat_id, message_thread_id, input_text)

    async def _call_interviewer(
        self, ctx: str, chat_id: int, message_thread_id: int | None, user_message: str
    ) -> None:
        """Invoca al modelo y responde al usuario, degradando con un mensaje si falla."""
        llm_input = self._build_llm_input(ctx, user_message)
        logger.debug(f"{ctx} entrada al LLM: {format_llm_input(llm_input)}")

        started = time.perf_counter()
        try:
            reply = await self._reply_with_interviewer(chat_id, llm_input)
        except AgentError as exc:
            await self._record_token_usage(
                ctx,
                chat_id,
                None,
                exc.token_usages
                or [self._unknown_usage(exc.code, (time.perf_counter() - started) * 1000)],
                (time.perf_counter() - started) * 1000,
            )
            logger.warning(
                "%s fallo controlado del modelo code=%s retryable=%s",
                ctx,
                exc.code,
                exc.retryable,
            )
            await self._send(
                chat_id,
                message_thread_id,
                self._message_for_agent_error(exc.code),
            )
            return
        except Exception:
            logger.exception(f"{ctx} fallo al invocar el modelo")
            await self._send(chat_id, message_thread_id, Constants.LLM_ERROR_MESSAGE)
            return
        elapsed_ms = (time.perf_counter() - started) * 1000
        turn = reply.turn

        if turn.status == "completed":
            if turn.report is None:
                raise RuntimeError("Completed interviewer result is missing report")
            llm_output = turn.report
        else:
            llm_output = turn.reply

        if not llm_output.strip():
            logger.error(f"{ctx} el modelo devolvio una respuesta vacia tras {elapsed_ms:.0f}ms")
            await self._send(chat_id, message_thread_id, Constants.LLM_ERROR_MESSAGE)
            return

        if elapsed_ms > Constants.SLOW_LLM_MS:
            logger.warning(f"{ctx} respuesta lenta del modelo: {elapsed_ms:.0f}ms")

        logger.info(f"{ctx} respuesta del LLM en {elapsed_ms:.0f}ms: {llm_output!r}")
        await self._send(chat_id, message_thread_id, llm_output)
        if turn.status == "completed":
            if turn.profile is None or turn.report is None:
                raise RuntimeError("Completed interviewer result is missing profile or report")
            conversation_message_id = await self._conversation_repository.complete_interview(
                chat_id,
                user_message,
                turn.reply,
                turn.profile,
                turn.report,
            )
        else:
            conversation_message_id = await self._conversation_repository.add_turn(
                chat_id, user_message, llm_output
            )
        await self._record_token_usage(
            ctx, chat_id, conversation_message_id, reply.token_usages, elapsed_ms
        )

    async def _generate_plan(
        self, ctx: str, chat_id: int, message_thread_id: int | None, user_message: str
    ) -> None:
        """``/train``: profile -> retrieval -> one LLM call -> persisted plan."""
        if self._trainer is None or self._exercise_retriever is None:
            logger.warning(f"{ctx} /train sin entrenador configurado")
            await self._send(chat_id, message_thread_id, Constants.TRAINER_UNAVAILABLE_MESSAGE)
            return

        profile = await self._conversation_repository.get_interviewer_profile(chat_id)
        if profile is None:
            logger.info(f"{ctx} /train sin perfil previo")
            await self._send(chat_id, message_thread_id, Constants.NO_PROFILE_MESSAGE)
            return

        await self._send(chat_id, message_thread_id, Constants.PLAN_GENERATING_MESSAGE)

        span = trace.get_current_span()
        retrieval_started = time.perf_counter()
        try:
            exercises = await self._exercise_retriever.retrieve(profile)
        except Exception:
            # No catalogue means no plan worth delivering: a mesocycle invented
            # from model memory is exactly what this agent exists to avoid.
            logger.exception(f"{ctx} fallo recuperando ejercicios")
            await self._send(chat_id, message_thread_id, Constants.TRAINER_UNAVAILABLE_MESSAGE)
            return
        span.set_attribute("rag.exercises_retrieved", len(exercises))
        span.set_attribute("rag.latency_ms", int((time.perf_counter() - retrieval_started) * 1000))
        span.set_attribute("rag.degraded", False)

        if not exercises:
            logger.error(f"{ctx} el catalogo de ejercicios devolvio 0 resultados")
            await self._send(chat_id, message_thread_id, Constants.TRAINER_UNAVAILABLE_MESSAGE)
            return

        started = time.perf_counter()
        try:
            reply = await self._trainer.generate_plan(profile, exercises)
        except AgentError as exc:
            await self._record_trainer_error(
                ctx, chat_id, message_thread_id, TrainerAction.GENERATE_PLAN, exc, started
            )
            return
        except Exception:
            logger.exception(f"{ctx} fallo al invocar al entrenador")
            await self._send(chat_id, message_thread_id, Constants.LLM_ERROR_MESSAGE)
            return
        elapsed_ms = (time.perf_counter() - started) * 1000
        turn = reply.turn

        if turn.status != "plan" or turn.plan is None or turn.report is None:
            # The model answered instead of planning (for example because the
            # catalogue looked unusable to it). Relay it, persist nothing.
            logger.warning(f"{ctx} el entrenador no devolvio un plan: status={turn.status}")
            await self._send(chat_id, message_thread_id, turn.reply)
            await self._record_token_usage(
                ctx,
                chat_id,
                None,
                reply.token_usages,
                elapsed_ms,
                AgentType.TRAINER.value,
            )
            return

        if elapsed_ms > Constants.SLOW_LLM_MS:
            logger.warning(f"{ctx} respuesta lenta del entrenador: {elapsed_ms:.0f}ms")
        logger.info(f"{ctx} plan generado en {elapsed_ms:.0f}ms")

        await self._send(chat_id, message_thread_id, turn.report)
        conversation_message_id = await self._conversation_repository.save_training_plan(
            chat_id, turn.plan, turn.report, user_message, turn.reply
        )
        await self._record_token_usage(
            ctx,
            chat_id,
            conversation_message_id,
            reply.token_usages,
            elapsed_ms,
            AgentType.TRAINER.value,
        )

    async def _answer_about_plan(
        self, ctx: str, chat_id: int, message_thread_id: int | None, user_message: str
    ) -> None:
        """Follow-up question about an existing plan."""
        if self._trainer is None or self._exercise_retriever is None:
            await self._send(chat_id, message_thread_id, Constants.TRAINER_UNAVAILABLE_MESSAGE)
            return

        stored_plan = await self._conversation_repository.get_current_plan(chat_id)
        if stored_plan is None:
            logger.warning(f"{ctx} sesion de entrenamiento activa sin plan almacenado")
            await self._send(chat_id, message_thread_id, Constants.NO_PLAN_MESSAGE)
            return

        profile = await self._conversation_repository.get_interviewer_profile(chat_id)
        span = trace.get_current_span()
        exercises = []
        if profile is not None:
            try:
                exercises = await self._exercise_retriever.retrieve(profile)
            except Exception:
                # Unlike /train, a question can still be answered from the plan
                # itself, so degrade instead of refusing.
                logger.warning(f"{ctx} respondiendo sin catalogo: la recuperacion fallo")
        span.set_attribute("rag.exercises_retrieved", len(exercises))
        span.set_attribute("rag.degraded", not exercises)

        history = await self._conversation_repository.get_recent(
            chat_id, self._trainer_history_window_messages, AgentType.TRAINER.value
        )

        started = time.perf_counter()
        try:
            reply = await self._trainer.answer(user_message, stored_plan.plan, history, exercises)
        except AgentError as exc:
            await self._record_trainer_error(
                ctx, chat_id, message_thread_id, TrainerAction.ANSWER_PLAN, exc, started
            )
            return
        except Exception:
            logger.exception(f"{ctx} fallo al invocar al entrenador")
            await self._send(chat_id, message_thread_id, Constants.LLM_ERROR_MESSAGE)
            return
        elapsed_ms = (time.perf_counter() - started) * 1000

        if not reply.turn.reply.strip():
            logger.error(f"{ctx} el entrenador devolvio una respuesta vacia")
            await self._send(chat_id, message_thread_id, Constants.LLM_ERROR_MESSAGE)
            return

        await self._send(chat_id, message_thread_id, reply.turn.reply)
        conversation_message_id = await self._conversation_repository.add_turn(
            chat_id, user_message, reply.turn.reply, AgentType.TRAINER.value
        )
        await self._record_token_usage(
            ctx,
            chat_id,
            conversation_message_id,
            reply.token_usages,
            elapsed_ms,
            AgentType.TRAINER.value,
        )

    async def _record_trainer_error(
        self,
        ctx: str,
        chat_id: int,
        message_thread_id: int | None,
        action: TrainerAction,
        exc: AgentError,
        started: float,
    ) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        await self._record_token_usage(
            ctx,
            chat_id,
            None,
            exc.token_usages or [self._unknown_usage(exc.code, elapsed_ms)],
            elapsed_ms,
            AgentType.TRAINER.value,
        )
        logger.warning(
            "%s fallo controlado del entrenador --> action=%s, code=%s retryable=%s",
            ctx,
            action,
            exc.code,
            exc.retryable,
        )
        await self._send(chat_id, message_thread_id, self._message_for_agent_error(exc.code))

    @staticmethod
    def _unknown_usage(code: AgentErrorCode, elapsed_ms: float) -> TokenUsage:
        return TokenUsage(
            model="unknown",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            status=code.value,
            latency_ms=int(elapsed_ms),
        )

    async def _record_token_usage(
        self,
        ctx: str,
        chat_id: int,
        conversation_message_id: int | None,
        token_usages: list[TokenUsage],
        elapsed_ms: float,
        agent: str = AgentType.INTERVIEWER.value,
    ) -> None:
        """Log + persist tokens per LLM call; skipped when the model reported no usage."""
        if not token_usages:
            return
        total_tokens = sum(usage.total_tokens for usage in token_usages)
        logger.info(f"{ctx} tokens consumidos: total={total_tokens} llamadas={len(token_usages)}")
        span = trace.get_current_span()
        span.set_attribute("llm.total_tokens", total_tokens)
        span.set_attribute("llm.calls", len(token_usages))
        for usage in token_usages:
            await self._conversation_repository.record_token_usage(
                chat_id=chat_id,
                agent=agent,
                model=usage.model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
                latency_ms=usage.latency_ms,
                status=usage.status,
                conversation_message_id=conversation_message_id,
            )

    async def _reply_with_interviewer(
        self,
        chat_id: int,
        llm_input: IAInput,
    ) -> InterviewerReply:
        history = await self._conversation_repository.get_recent(
            chat_id,
            self._history_window_messages,
        )
        return await self._interviewer.respond(llm_input.get_user_message(), history)

    def _build_llm_input(self, ctx: str, user_message: str) -> IAInput:
        interviewer_agent = agent_factory.build_interviewer_agent()
        system_prompt_with_context = interviewer_agent.insert_context("")
        if not system_prompt_with_context:
            logger.debug(f"{ctx} el system prompt va vacio: el modelo no recibe instrucciones")
        return IAInput([
            IAMessage(role="system", message=system_prompt_with_context),
            IAMessage(message=user_message),
        ])

    async def _send(self, chat_id: int, message_thread_id: int | None, text: str) -> None:
        await self._bot.send_message(
            chat_id=chat_id, message_thread_id=message_thread_id, text=text
        )

    async def _notify_server_error(self, message: Message | None, ctx: str) -> None:
        if message is None:
            return
        try:
            await self._bot.send_message(
                chat_id=message.chat_id, text=Constants.SERVER_ERROR_MESSAGE
            )
        except Exception:
            logger.exception(f"{ctx} tampoco se pudo avisar al usuario del error")

    @staticmethod
    def _message_for_agent_error(code: AgentErrorCode) -> str:
        messages = {
            AgentErrorCode.AUTHENTICATION: Constants.LLM_AUTHENTICATION_ERROR_MESSAGE,
            AgentErrorCode.QUOTA: Constants.LLM_QUOTA_ERROR_MESSAGE,
            AgentErrorCode.RATE_LIMITED: Constants.LLM_RATE_LIMIT_ERROR_MESSAGE,
            AgentErrorCode.INVALID_REQUEST: Constants.LLM_INVALID_REQUEST_ERROR_MESSAGE,
            AgentErrorCode.OUTPUT_LIMIT: Constants.LLM_OUTPUT_LIMIT_ERROR_MESSAGE,
            AgentErrorCode.TIMEOUT: Constants.LLM_TIMEOUT_ERROR_MESSAGE,
            AgentErrorCode.UNAVAILABLE: Constants.LLM_UNAVAILABLE_ERROR_MESSAGE,
            AgentErrorCode.INVALID_OUTPUT: Constants.LLM_INVALID_OUTPUT_ERROR_MESSAGE,
        }
        return messages[code]

    @staticmethod
    def _build_context(update: Update, message: Message | None) -> str:
        """Prefijo comun a todas las trazas de una peticion, para poder correlacionarlas."""
        chat_id = message.chat_id if message is not None else Constants.UNKNOWN_ID
        message_id = message.message_id if message is not None else Constants.UNKNOWN_ID
        thread_id = message.message_thread_id if message is not None else None
        return (
            f"[update={update.update_id} chat={chat_id} thread={thread_id} "
            f"msg={message_id} user={user_label(message)} "
            f"telegram_user_id={telegram_user_id(message)}]"
        )
