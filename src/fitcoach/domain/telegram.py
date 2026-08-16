from enum import Enum


class Commands(Enum):
    START = "/start"
    INTERVIEW = "/interview"
    DOUBTS = "/doubts"
    PROGRESS = "/progress"

    @classmethod
    def from_value(cls, value: str) -> "Commands | None":
        try:
            return cls(value)
        except ValueError:
            return None

    @classmethod
    def get_commands_str(cls) -> str:
        bullet_separator = "\n- "
        return (
            f"- {bullet_separator.join(cmd.value for cmd in cls if cmd.name != cls.START.name)}\n"
        )
