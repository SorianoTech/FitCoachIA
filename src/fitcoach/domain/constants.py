"""Constantes compartidas: textos al usuario, patrones de limpieza y umbrales."""

from typing import Final

import regex

from fitcoach.domain.telegram import Commands


class Constants:
    """Valores fijos usados en toda la aplicacion.

    Se agrupan aqui para que los textos que ve el usuario y los umbrales de
    trazas puedan revisarse en un unico sitio, sin bucear por los controladores.
    """

    # --- Mensajes enviados al usuario por Telegram ---
    WELCOME_MESSAGE: Final = f"""
Bienvenido a FitCoachIA, tu entrenador personal de confianza!
Por favor, haz uso de los siguientes comandos:
{Commands.get_commands_str()}
Tu nueva vida te espera, ¡Adelante!
"""
    INVALID_TEXT_MESSAGE: Final = (
        "Ups! Parece que no te he logrado entender ... ¿Puedes repetirmelo, por favor?"
    )
    NO_CONTENT_MESSAGE: Final = "I didn't receive any information. Please, send it again .... "
    NOT_IMPLEMENTED_MESSAGE: Final = "Option not implemented yet"
    LLM_ERROR_MESSAGE: Final = "Ops, our brains exploded ... try it again"
    SERVER_ERROR_MESSAGE: Final = "Ops, our server has an error. Try again past 5 minutes"

    # --- Mensaje con el que se siembra la conversacion del modelo ---
    INTERVIEW_SEED_MESSAGE: Final = (
        "New interview conversation about a body change was initiated. "
        "What do you need to know about our new client to change its life?"
    )

    # --- Limpieza del texto de entrada ---
    EMOJI_PATTERN: Final = regex.compile(r"[\p{Extended_Pictographic}\p{Regional_Indicator}️‍⃣]")
    WHITESPACE_PATTERN: Final = regex.compile(r"\s+")

    # --- Trazas ---
    MAX_LOGGED_CHARS: Final = 300
    SLOW_LLM_MS: Final = 30_000
    UNKNOWN_ID: Final = -1
    UNKNOWN_USER: Final = "desconocido"
