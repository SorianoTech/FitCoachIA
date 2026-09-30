"""Cuota de consumo de LLM por chat. Cada comando se corta a un nivel distinto."""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Final

from fitcoach.domain.telegram import Commands


class UsageTier(StrEnum):
    """Nivel de consumo al que se corta un comando."""

    UNLIMITED = "unlimited"  # no invoca al modelo
    SOFT = "soft"  # se corta en el umbral blando: lo caro cae primero
    HARD = "hard"  # se corta en el limite


COMMAND_TIERS: Final[dict[Commands | None, UsageTier]] = {
    Commands.START: UsageTier.UNLIMITED,
    Commands.DOUBTS: UsageTier.UNLIMITED,
    Commands.PROGRESS: UsageTier.UNLIMITED,
    Commands.INTERVIEW: UsageTier.SOFT,
    None: UsageTier.HARD,  # texto libre
}


@dataclass(frozen=True)
class UsageLimits:
    """Umbrales ya resueltos en tokens, calculados a partir de la configuracion."""

    hard_tokens: int
    soft_tokens: int
    window: timedelta

    def tier_for(self, command: Commands | None) -> UsageTier:
        return COMMAND_TIERS[command]

    def limit_for(self, command: Commands | None) -> int | None:
        """Tokens permitidos antes de cortar; None si el comando no consume modelo."""
        match self.tier_for(command):
            case UsageTier.UNLIMITED:
                return None
            case UsageTier.SOFT:
                return self.soft_tokens
            case UsageTier.HARD:
                return self.hard_tokens
