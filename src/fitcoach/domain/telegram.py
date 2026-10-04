from difflib import get_close_matches
from enum import Enum


class Commands(Enum):
    START = ("/start", "")
    INTERVIEW = ("/interview", "Se inicia una nueva entrevista")
    TRAIN = ("/train", "Genera tu plan de entrenamiento de 4 semanas")
    ADD_EXERCISE = ("/add_exercise", "Propón un ejercicio para el catálogo")
    REVIEW_EXERCISES = ("/review_exercises", "Revisa propuestas de ejercicios")
    APPROVE_EXERCISE = ("/approve_exercise", "Aprueba una propuesta de ejercicio")
    REJECT_EXERCISE = ("/reject_exercise", "Rechaza una propuesta de ejercicio")
    DOUBTS = ("/doubts", "Consultar cualquier duda acerca de tu perfil")
    PROGRESS = ("/progress", "Comprobar tu progreso en base a tu perfil y los logros conseguidos")

    descripcion: str

    def __new__(cls, valor: str, descripcion: str) -> "Commands":
        obj = object.__new__(cls)
        obj._value_ = valor
        obj.descripcion = descripcion
        return obj

    @classmethod
    def from_value(cls, value: str) -> "Commands | None":
        normalized = value.partition("@")[0]
        return next((cmd for cmd in cls if cmd.value == normalized), None)

    @classmethod
    def suggest(cls, value: str) -> str | None:
        normalized = value.partition("@")[0]
        matches = get_close_matches(normalized, [cmd.value for cmd in cls], n=1, cutoff=0.6)
        return matches[0] if matches else None

    @classmethod
    def get_commands_str(cls) -> str:
        bullet_separator = "\n- "
        hidden = {
            cls.START,
            cls.REVIEW_EXERCISES,
            cls.APPROVE_EXERCISE,
            cls.REJECT_EXERCISE,
        }
        lines = [f"{cmd.value} - {cmd.descripcion}" for cmd in cls if cmd not in hidden]
        return f"- {bullet_separator.join(lines)}\n"
