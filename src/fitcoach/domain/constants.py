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
        "Tu entrevista ya está completada. Envía /train para generar tu plan de entrenamiento, "
        "o /interview si quieres actualizar tu perfil."
    )

    # --- Mensajes del agente entrenador ---
    NO_PROFILE_MESSAGE: Final = (
        "Todavía no tengo tu perfil. Envía /interview para hacer la entrevista inicial y "
        "después podré prepararte el plan."
    )
    PLAN_GENERATING_MESSAGE: Final = "Estoy diseñando tu plan de 4 semanas. Dame unos segundos ..."
    NO_PLAN_MESSAGE: Final = (
        "Aún no tienes un plan de entrenamiento. Envía /train y te preparo uno."
    )
    TRAINER_UNAVAILABLE_MESSAGE: Final = (
        "No he podido consultar el catálogo de ejercicios ahora mismo. "
        "Inténtalo de nuevo en unos minutos."
    )
    TRAINING_REVIEW_QUESTIONS: Final = {
        "adherence": "¿Cuántas sesiones has realizado frente a las previstas? Puedes decir que no lo sabes.",
        "results": "¿Qué mejoras, estancamientos o dificultades has notado? Indica resultados concretos si los tienes.",
        "recovery": "¿Cómo han sido la fatiga, el descanso y el esfuerzo? ¿Ha cambiado tu sueño?",
        "discomfort": "¿Has tenido dolor o molestias nuevas? Indica restricciones actuales; no entrenes con dolor.",
        "preferences": "¿Qué ejercicios quieres mantener o cambiar, y por qué?",
        "changes": "¿Han cambiado tu objetivo, días disponibles, minutos por sesión, entorno o material? Si no, responde «sin cambios».",
    }
    TRAINING_CLOSURE_QUESTION: Final = (
        "¿Has terminado el bloque, incluida la descarga?\n\n"
        "Si te ha ido bien, sin molestias nuevas y quieres mantener objetivo, horarios y "
        "material, podemos preparar el siguiente.\n"
        "Elige abajo o responde «terminé y todo bien», «quiero ajustar algo» o «todavía no»."
    )
    TRAINING_REVIEW_CHOICE: Final = (
        "¿Cómo te ha ido el bloque?\n\n"
        "Elige «Todo bien» si no hay molestias nuevas ni cambios de objetivo, horarios o "
        "material. Si quieres ajustar algo, cuéntamelo con tus palabras."
    )
    TRAINING_OPEN_REVIEW: Final = (
        "Cuéntame cómo te ha ido y qué quieres cambiar: algo que te costó, molestias, "
        "ejercicios que no te convencen o cambios de tiempo y material. "
        "Puedes explicarlo con tus palabras; indica también si hay molestias nuevas."
    )
    TRAINING_REVIEW_UNKNOWN: Final = "No informado; no inferir resultados ni ejecución."
    TRAINING_SWAP_PICKER: Final = "¿Qué ejercicio quieres cambiar? Elige abajo."
    TRAINING_SWAP_PICKER_WEEK: Final = "¿Qué ejercicio de la semana {week} quieres cambiar?\nElige abajo. Tu plan seguirá igual hasta que confirmes la sustitución."
    TRAINING_SWAP_WEEK: Final = (
        "¿Desde qué semana quieres aplicar el cambio? Las anteriores se conservan."
    )
    TRAINING_SWAP_REASON: Final = "¿Por qué quieres cambiarlo?"
    TRAINING_SWAP_REASON_INPUT: Final = (
        "Cuéntame el motivo. Si falta material, indica cuál; si hay molestias, descríbelas."
    )
    TRAINING_SWAP_REASONS: Final = {
        "equipment": "No tengo el material",
        "preference": "Prefiero otro ejercicio",
        "difficulty": "Me resulta difícil",
        "other": "Otro motivo",
    }
    TRAINING_SWAP_NAVIGATION: Final = {"previous": "Anterior", "next": "Siguiente"}
    TRAINING_SWAP_WEEK_BUTTON: Final = "Semana {week}"
    TRAINING_SWAP_DAY_BUTTON: Final = "Día {day} · {name}"
    TRAINING_EQUIPMENT_QUESTION: Final = "¿Qué material tienes disponible para entrenar? Indica el tipo de pesas, máquinas o accesorios."
    TRAINING_REVIEW_BUTTONS: Final = {
        "good": "Terminé y todo bien",
        "closed_good": "Todo bien",
        "changes": "Terminé, pero quiero ajustar algo",
        "closed_changes": "Quiero ajustar algo",
    }
    TRAINING_QUICK_REVIEW: Final = {
        "adherence": "Mesociclo terminado; número de sesiones realizadas no informado.",
        "results": "El usuario declara que le ha ido bien; no aporta mejoras ni cargas concretas.",
        "recovery": "El usuario declara que todo ha ido bien; sueño y fatiga no cuantificados.",
        "discomfort": "El usuario confirma que no hay molestias nuevas; conservar restricciones previas.",
        "preferences": "Mantener ejercicios principales y progresar de forma prudente.",
        "changes": "Sin cambios de objetivo, horarios ni material; conservar el perfil vigente.",
    }
    TRAINING_DUE_MESSAGE: Final = (
        "Ha llegado la fecha prevista de cierre de tu mesociclo. Esto no significa que hayas "
        "completado las sesiones. Envía /train para revisarlo y preparar un borrador del siguiente, "
        "/train posponer AAAA-MM-DD para posponer o /train avisos off para desactivar avisos."
    )
    TRAINING_LEGACY_MESSAGE: Final = (
        "Tu plan anterior no tiene una fecha de inicio confirmada. Indícala con "
        "/train inicio AAAA-MM-DD, o envía /train si ya has terminado y quieres renovarlo."
    )
    TRAINING_CONTROLS_MESSAGE: Final = (
        "Controles: /train para revisar y renovar; /train cambiar ID SEMANA MOTIVO para "
        "sustituir las ocurrencias desde esa semana; /train elegir PROPUESTA OPCIÓN; "
        "/train confirmar PROPUESTA [AAAA-MM-DD]; /train cancelar; "
        "/train posponer AAAA-MM-DD; /train avisos on|off. Consulta de solo lectura: "
        "envía /train consulta seguido de tu pregunta."
        " Para corregir la revisión: /train editar CAMPO TEXTO "
        "(adherence, results, recovery, discomfort, preferences, changes)."
    )
    TRAINING_SWAP_QUESTION: Final = (
        "Indica el ID del ejercicio, la semana actual (1-4) y el motivo, por ejemplo "
        "«101 2 no dispongo de barra». Se propondrá cambiar sus ocurrencias desde esa "
        "semana; las anteriores no cambian."
    )
    TRAINING_DRAFT_SWAP_QUESTION: Final = (
        "Indica el ID del ejercicio del borrador, la primera semana afectada (1 para todo "
        "el nuevo bloque) y el motivo. El plan vigente no se modificará hasta confirmar."
    )
    TRAINING_SAFETY_MESSAGE: Final = (
        "Con dolor nuevo o síntomas preocupantes, detén la actividad afectada y consulta "
        "a un profesional cualificado. No generaré una sustitución como tratamiento. "
        "Usa /train cancelar para cerrar esta propuesta."
    )
    TRAINING_CANCELLED_MESSAGE: Final = "Propuesta cancelada. Tu plan vigente no ha cambiado."
    TRAINING_CONFLICT_MESSAGE: Final = (
        "La propuesta ha cambiado, está en proceso o ya no corresponde al plan vigente. "
        "Envía /train para consultar su estado."
    )
    TRAINING_NO_ALTERNATIVES_MESSAGE: Final = (
        "No hay alternativas verificadas compatibles con el grupo muscular y material declarado. "
        "Tu plan no ha cambiado; aclara el material o cancela la propuesta."
    )
    TRAINING_GENERATING_MESSAGE: Final = "Estoy preparando un borrador; tu plan vigente no cambia."
    TRAINING_ACCEPTED_MESSAGE: Final = (
        "Propuesta confirmada y guardada como nueva versión de tu plan."
    )
    TRAINING_BUSY_MESSAGE: Final = (
        "El borrador está generándose. Usa /train para consultar su estado."
    )
    TELEGRAM_MAX_MESSAGE_CHARS: Final = 4096
    TRAINING_BUTTONS: Final = {
        "start": "Empezar hoy",
        "apply": "Aplicar cambio",
        "date": "Elegir fecha",
        "swap": "Cambiar un ejercicio",
        "cancel": "Descartar borrador",
        "finished": "Sí, he terminado",
        "not_yet": "Todavía no (recordar en 7 días)",
        "tomorrow": "Mañana",
        "monday": "Próximo lunes",
        "other": "Otra fecha",
        "details": "Ver plan completo y detalles",
    }
    TRAINING_DATE_PICKER: Final = "¿Cuándo quieres empezar el nuevo mesociclo?"
    TRAINING_DATE_INPUT: Final = "Escribe la fecha de inicio con formato AAAA-MM-DD (UTC)."
    TRAINING_CALLBACK_INVALID: Final = (
        "Este botón ya no corresponde a la propuesta vigente. Envía /train para verla."
    )
    TRAINING_CALLBACK_PRIVATE: Final = (
        "Solo el propietario puede confirmar propuestas en su chat privado."
    )
    TRAINING_PREVIEW: Final = {
        "renewal": "TU SIGUIENTE MESOCICLO",
        "swap": "TU CAMBIO DE EJERCICIO",
        "pending": "Propuesta pendiente de tu aprobación",
        "schedule": "{days} días/semana · sesiones de hasta {minutes} min",
        "sessions": "TUS SESIONES · SEMANA 1",
        "day": "Día {day} · {focus} · {minutes} min",
        "more": "  + {count} ejercicios más",
        "progression": "PROGRESIÓN · 4 SEMANAS",
        "week": "S{week} · {intensity} · {sets} series{rpe}",
        "rpe": " · RPE máx. {value:g}",
        "sets_note": "Series totales prescritas por semana, no realizadas.",
        "swap_scope": "Sustitución del ejercicio {id} desde la semana {week}.\nLas semanas anteriores y las fechas del ciclo no cambian.",
        "restrictions": "IMPORTANTE · RESTRICCIONES",
        "flags": "Consulta a un profesional antes de empezar: {flags}",
        "footer": "¿Te encaja? Confirma abajo o consulta el plan completo antes de decidir.\nTu plan vigente no cambia hasta que aceptes.",
        "full": "PLAN COMPLETO PROPUESTO",
        "report": "POR QUÉ ESTE PLAN",
        "review": "TU REVISIÓN · CAMBIOS INTERPRETADOS",
        "profile": "DATOS QUE HEMOS TENIDO EN CUENTA",
        "prescription": "  • {name} — {sets} × {reps} · descanso {rest}s{rpe}",
        "exercise_rpe": " · RPE {value}",
        "full_week": "SEMANA {week} · {intensity}",
        "progression_notes": "INDICACIONES DE PROGRESIÓN",
        "notes": "    {notes}",
        "truncated": "Hay más información en «Ver plan completo y detalles».",
    }
    TRAINING_GOAL_LABELS: Final = {
        "gain_muscle": "Ganar músculo",
        "lose_fat": "Perder grasa",
        "performance": "Mejorar rendimiento",
    }
    TRAINING_ENVIRONMENT_LABELS: Final = {
        "gym": "Gimnasio",
        "home": "Casa",
        "outdoors": "Exterior",
        "mixed": "Mixto",
    }
    TRAINING_INTENSITY_LABELS: Final = {
        "accumulation": "Acumulación",
        "intensification": "Intensificación",
        "peak": "Pico",
        "deload": "Descarga",
    }
    TRAINING_MESSAGES: Final = {
        "closed": "Cierre confirmado. Envía /train para continuar la revisión del siguiente bloque.",
        "status": "Mesociclo iniciado el {start}; cierre previsto: {end}. La ejecución no se registra automáticamente. Envía /train si ya has terminado.",
        "unknown_date": "sin confirmar",
        "reminders_saved": "Preferencia de avisos guardada.",
        "reminders_usage": "Usa /train avisos on|off.",
        "date_usage": "Indica una fecha con formato AAAA-MM-DD.",
        "start_future": "El inicio del plan anterior no puede estar en el futuro.",
        "postpone_past": "La nueva fecha prevista debe estar en el futuro.",
        "confirm_usage": "Usa /train confirmar PROPUESTA [AAAA-MM-DD].",
        "new_start_past": "El nuevo mesociclo no puede empezar en el pasado.",
        "choose_usage": "Usa /train elegir PROPUESTA OPCIÓN.",
        "pending_review": "Hay una revisión abierta. Indica los cambios en ella o usa /train cancelar primero.",
        "invalid_id": "Indica un identificador numérico válido.",
        "positive_id": "El identificador debe ser positivo.",
        "invalid_date": "La fecha debe ser válida y usar el formato AAAA-MM-DD (UTC).",
        "review_ready": "Revisión recogida. Responde «generar» para reintentar el borrador o /train cancelar.",
        "equipment_clarification": "Aclara el material con /train editar changes ... antes de generar.",
        "invalid_week": "La semana actual debe estar entre 1 y 4.",
        "closed_swap": "El ciclo está cerrado. Cancela la sustitución y usa /train para renovar.",
        "unknown_exercise": "Ese ejercicio no pertenece al plan vigente.",
        "no_pending_occurrences": "No hay ocurrencias de ese ejercicio en las semanas pendientes indicadas.",
        "metadata_clarification": "Necesito aclarar el material o los metadatos del ejercicio antes de proponer alternativas.",
        "invalid_option": "Elige una de las opciones propuestas.",
        "swap_report": "Sustitución: {source} → {name}, desde la semana {week}. {reason} Prescripción de referencia: {sets} series, {reps} repeticiones, {rest}s de descanso; RPE {rpe}. Las series se adaptan a la progresión de cada semana y se conserva la descarga.",
        "unspecified_rpe": "no indicado",
        "alternatives_header": "Alternativas propuestas; todavía no se ha modificado el plan:\n",
        "choose": "Elige una alternativa con los botones. También puedes usar /train elegir {id} OPCIÓN o /train cancelar.",
        "draft": "Borrador {id} (no activo):\n{report}",
        "context": "Contexto propuesto: objetivo {goal}; {days} días/semana, {minutes} min/sesión; entorno {environment}; material {equipment}; sueño {sleep} h; restricciones {injuries}. Confirma solo si refleja tu situación actual.",
        "no_injuries": "sin lesiones declaradas",
        "confirm_draft": "Revisa los cambios y el contexto y usa los botones para confirmar, elegir fecha o descartar. Como alternativa: /train confirmar {id} (inicio hoy) o /train cancelar. Las sustituciones conservan las fechas del bloque.",
    }

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
        "Has alcanzado la cuota para iniciar entrevistas o generar planes y sustituciones. "
        "Puedes continuar las consultas y confirmar o cancelar propuestas pendientes."
    )
    QUOTA_EXCEEDED_MESSAGE: Final = (
        "Has alcanzado el límite de uso por hoy. Vuelve a intentarlo más tarde."
    )
