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
    LLM_AUTHENTICATION_ERROR_MESSAGE: Final = (
        "No puedo conectar con el modelo por un problema de configuración. "
        "Avísanos para que podamos solucionarlo."
    )
    LLM_QUOTA_ERROR_MESSAGE: Final = (
        "El servicio de inteligencia artificial no tiene crédito disponible ahora mismo. "
        "Inténtalo más tarde."
    )
    LLM_RATE_LIMIT_ERROR_MESSAGE: Final = (
        "El servicio está recibiendo demasiadas solicitudes. Inténtalo de nuevo en unos minutos."
    )
    LLM_INVALID_REQUEST_ERROR_MESSAGE: Final = (
        "No he podido procesar esta solicitud. Prueba a enviarla de nuevo."
    )
    LLM_OUTPUT_LIMIT_ERROR_MESSAGE: Final = (
        "No he podido terminar la respuesta del modelo. Inténtalo de nuevo en unos minutos."
    )
    LLM_TIMEOUT_ERROR_MESSAGE: Final = (
        "El modelo está tardando demasiado en responder. Inténtalo de nuevo en unos minutos."
    )
    LLM_UNAVAILABLE_ERROR_MESSAGE: Final = (
        "El servicio de inteligencia artificial no está disponible temporalmente. "
        "Inténtalo de nuevo en unos minutos."
    )
    LLM_INVALID_OUTPUT_ERROR_MESSAGE: Final = (
        "No he podido interpretar la respuesta del modelo. Inténtalo de nuevo."
    )
    SERVER_ERROR_MESSAGE: Final = "Ops, our server has an error. Try again past 5 minutes"
    INTERVIEW_COMPLETED_MESSAGE: Final = (
        "Tu entrevista ya está completada. Envía /interview si quieres actualizar tu perfil."
    )

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
    # Telegram limita a un mensaje por segundo y chat; esperas mayores no compensan.
    MAX_TELEGRAM_RETRY_SECONDS: Final = 5
    UNKNOWN_USER: Final = "desconocido"

    QUOTA_SOFT_MESSAGE: Final = (
        "No puedes iniciar una entrevista nueva por hoy, "
        "pero puedes seguir con la conversación actual."
    )
    QUOTA_EXCEEDED_MESSAGE: Final = (
        "Has alcanzado el límite de uso por hoy. Vuelve a intentarlo más tarde."
    )
