"""Telegram webhook controller: receive updates and reply via the Bot API."""

import logging

import regex
from fastapi import APIRouter, Depends, HTTPException, Request, status
from telegram import Bot, Message, Update

from fitcoach.domain.entities import IAInput, IAMessage
from fitcoach.domain.telegram import Commands
from fitcoach.infrastructure.bot.telegram_bot import get_bot
from fitcoach.service.agent import agent_factory
from fitcoach.service.llm.llm_caller import LLM, get_llm

logger = logging.getLogger(__name__)

webhook = APIRouter(prefix="/webhook", tags=["telegram"])

WELCOME_MESSAGE = f"""
Bienvenido a FitCoachIA, tu entrenador personal de confianza!
Por favor, haz uso de los siguientes comandos:
{Commands.get_commands_str()}
Tu nueva vida te espera, ¡Adelante!
"""
INVALID_TEXT_MESSAGE = (
    "Ups! Parece que no te he logrado entender ... ¿Puedes repetirmelo, por favor?"
)

_EMOJI_PATTERN = regex.compile(
    r"[\p{Extended_Pictographic}\p{Regional_Indicator}\uFE0F\u200D\u20E3]"
)
_WHITESPACE_PATTERN = regex.compile(r"\s+")


def remove_emojis(text: str) -> str:
    """Strip emoji, keeping letters, digits, punctuation and ordinary symbols.

    Whitespace is collapsed but not rebalanced around the removal, so a padded
    emoji leaves its separator behind: "¡Hola 👋, x" -> "¡Hola , x".
    """
    without_emojis = _EMOJI_PATTERN.sub("", text)
    return _WHITESPACE_PATTERN.sub(" ", without_emojis).strip()


async def parse_update(request: Request) -> Update:
    """Build a ``telegram.Update`` from the raw webhook body.

    FastAPI can only auto-bind Pydantic models, and ``telegram.Update`` is not
    one, so we read the raw JSON body and hand back a real library object.
    """
    try:
        data = await request.json()
    except ValueError as exc:
        logger.warning(f"Malformed webhook body received: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON body",
        ) from exc
    return Update.de_json(data)


@webhook.post("/response")
async def telegram_webhook(
    update: Update = Depends(parse_update),
    bot: Bot = Depends(get_bot),
    llm: LLM = Depends(get_llm),
) -> dict[str, bool]:
    message: Message | None = update.effective_message
    updated_message: Message | None = update.edited_message
    chat_id = -1
    message_id = -1
    updated_message_id = -1
    message_thread_id = -1
    update_id = -1

    if message is not None:
        chat_id = message.chat_id
        message_id = message.message_id
        message_thread_id = message.message_thread_id
        logger.info(
            f"[Chat ID {chat_id} - Chat theme ID {message_thread_id} - Message ID {message_id}]"
        )

    if updated_message is not None:
        chat_id = updated_message.chat_id
        updated_message_id = updated_message.message_id
        message_thread_id = updated_message.message_thread_id
        logger.info(
            f"[Chat ID {chat_id} - Chat theme ID {message_thread_id} - Updated message ID {updated_message_id}]"
        )

    if message is None or not message.text:
        logger.debug(f"Update {update_id} ignored: no message or text")
        await bot.send_message(
            chat_id=chat_id, text="I didn't receive any information. Please, send it again .... "
        )
        return {"ok": True}

    input_text = remove_emojis(message.text)
    if not input_text:
        # Nothing but emojis/whitespace survived the cleanup.
        logger.error(f"Chat {chat_id} sent an emoji/whitespace-only message")
        await bot.send_message(
            chat_id=chat_id, message_thread_id=message_thread_id, text=INVALID_TEXT_MESSAGE
        )
        return {"ok": True}

    command = Commands.from_value(input_text.split(maxsplit=1)[0])
    logger.debug(f"Webhook command identified: {command}")
    match command:
        case Commands.START:
            logger.debug("Command START identified")
            logger.info(f"Chat {chat_id} started a conversation")
            await bot.send_message(
                chat_id=chat_id, message_thread_id=message_thread_id, text=WELCOME_MESSAGE
            )
        case Commands.INTERVIEW:
            logger.debug("Command INTERVIEW identified")
            logger.info(f"Chat {chat_id} started a new interview")
            interviewer_agent = agent_factory.build_interviewer_agent()
            system_prompt_with_context = interviewer_agent.insert_context("")
            llm_input = IAInput(
                [
                    IAMessage(role="system", message=system_prompt_with_context),
                    IAMessage(
                        message="New interview conversation about a body change was initiated. What do you need to know about our new client to change its life?"
                    ),
                ]
            )
            logger.debug(f"LLM input message: {llm_input}")
            llm_output = await llm.chat(messages=llm_input)
            await bot.send_message(
                chat_id=message.chat_id, message_thread_id=message_thread_id, text=llm_output
            )
            return {"ok": True}
        case Commands.DOUBTS:
            logger.debug("Command DOUBTS identified")
            logger.info(f"Chat {chat_id} message not implemented")
            await bot.send_message(
                chat_id=message.chat_id,
                message_thread_id=message_thread_id,
                text="Option not implemented yet",
            )
            return {"ok": True}  # TODO: route to the doubts/Q&A flow
        case Commands.PROGRESS:
            logger.debug("command PROGRESS identified")
            logger.info(f"Chat {chat_id} message not implemented")
            await bot.send_message(
                chat_id=message.chat_id,
                message_thread_id=message_thread_id,
                text="Option not implemented yet",
            )
            return {"ok": True}
        case None:
            logger.debug("No command identified")
            logger.info(f"Chat {chat_id} with a free chat conversation")
            interviewer_agent = agent_factory.build_interviewer_agent()
            system_prompt_with_context = interviewer_agent.insert_context("")
            llm_input = IAInput(
                [
                    IAMessage(role="system", message=system_prompt_with_context),
                    IAMessage(message=input_text),
                ]
            )
            logger.debug(f"LLM input message: {llm_input}")
            llm_output = await llm.chat(messages=llm_input)
            await bot.send_message(
                chat_id=message.chat_id, message_thread_id=message_thread_id, text=llm_output
            )
            return {"ok": True}

    return {"ok": True}
