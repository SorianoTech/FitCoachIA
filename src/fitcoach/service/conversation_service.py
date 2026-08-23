"""Logica de conversacion: decide que responder a cada update de Telegram.

La capa de API solo traduce HTTP; toda la decision de negocio (que comando se
ha pedido, que se manda al modelo y que se le contesta al usuario) vive aqui.
"""

import logging
import time

from telegram import Bot, Message, Update

from fitcoach.domain.constants import Constants
from fitcoach.domain.entities import IAInput, IAMessage
from fitcoach.domain.telegram import Commands
from fitcoach.service.agent import agent_factory
from fitcoach.service.llm.llm_caller import LLM

logger = logging.getLogger(__name__)


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

    def __init__(self, bot: Bot, llm: LLM) -> None:
        self._bot = bot
        self._llm = llm

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

        match command:
            case Commands.START:
                await self._send(chat_id, message_thread_id, Constants.WELCOME_MESSAGE)
            case Commands.INTERVIEW:
                await self._reply_with_llm(
                    ctx, chat_id, message_thread_id, Constants.INTERVIEW_SEED_MESSAGE
                )
            case Commands.DOUBTS | Commands.PROGRESS:
                # TODO: route to the doubts/Q&A and progress-tracking flows
                logger.info(f"{ctx} opcion todavia no implementada")
                await self._send(chat_id, message_thread_id, Constants.NOT_IMPLEMENTED_MESSAGE)
            case None:
                await self._reply_with_llm(ctx, chat_id, message_thread_id, input_text)

    async def _reply_with_llm(
        self, ctx: str, chat_id: int, message_thread_id: int | None, user_message: str
    ) -> None:
        """Invoca al modelo y responde al usuario, degradando con un mensaje si falla."""
        llm_input = self._build_llm_input(ctx, user_message)
        logger.debug(f"{ctx} entrada al LLM: {format_llm_input(llm_input)}")

        started = time.perf_counter()
        try:
            llm_output = await self._llm.chat(messages=llm_input)
        except Exception:
            logger.exception(f"{ctx} fallo al invocar el modelo")
            await self._send(chat_id, message_thread_id, Constants.LLM_ERROR_MESSAGE)
            return
        elapsed_ms = (time.perf_counter() - started) * 1000

        if not llm_output.strip():
            logger.error(f"{ctx} el modelo devolvio una respuesta vacia tras {elapsed_ms:.0f}ms")
            await self._send(chat_id, message_thread_id, Constants.LLM_ERROR_MESSAGE)
            return

        if elapsed_ms > Constants.SLOW_LLM_MS:
            logger.warning(f"{ctx} respuesta lenta del modelo: {elapsed_ms:.0f}ms")

        logger.info(f"{ctx} respuesta del LLM en {elapsed_ms:.0f}ms: {llm_output!r}")
        await self._send(chat_id, message_thread_id, llm_output)

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
    def _build_context(update: Update, message: Message | None) -> str:
        """Prefijo comun a todas las trazas de una peticion, para poder correlacionarlas."""
        chat_id = message.chat_id if message is not None else Constants.UNKNOWN_ID
        message_id = message.message_id if message is not None else Constants.UNKNOWN_ID
        thread_id = message.message_thread_id if message is not None else None
        return (
            f"[update={update.update_id} chat={chat_id} thread={thread_id} "
            f"msg={message_id} user={user_label(message)}]"
        )
