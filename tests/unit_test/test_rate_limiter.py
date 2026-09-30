"""Politica de cuota: que nivel corresponde a cada comando y en que umbral corta."""

from datetime import timedelta

import pytest

from fitcoach.domain.rate_limiter import COMMAND_TIERS, UsageLimits, UsageTier
from fitcoach.domain.telegram import Commands

_LIMITS = UsageLimits(hard_tokens=1_000, soft_tokens=900, window=timedelta(hours=24))


class TestCommandTiers:
    def test_every_command_has_an_assigned_tier(self) -> None:
        """Guarda de extensibilidad: un comando nuevo sin nivel se colaria sin cuota."""
        assert set(COMMAND_TIERS) == {*Commands, None}

    @pytest.mark.parametrize("command", [Commands.START, Commands.DOUBTS, Commands.PROGRESS])
    def test_commands_that_never_call_the_model_have_no_limit(self, command: Commands) -> None:
        assert _LIMITS.limit_for(command) is None

    def test_starting_an_interview_is_cut_at_the_soft_threshold(self) -> None:
        assert _LIMITS.tier_for(Commands.INTERVIEW) is UsageTier.SOFT
        assert _LIMITS.limit_for(Commands.INTERVIEW) == 900

    def test_free_text_is_cut_at_the_hard_threshold(self) -> None:
        assert _LIMITS.tier_for(None) is UsageTier.HARD
        assert _LIMITS.limit_for(None) == 1_000

    def test_the_expensive_command_is_never_cut_later_than_free_text(self) -> None:
        """La degradacion escalonada solo sirve si lo caro cae primero."""
        interview = _LIMITS.limit_for(Commands.INTERVIEW)
        free_text = _LIMITS.limit_for(None)

        assert interview is not None
        assert free_text is not None
        assert interview <= free_text

    def test_an_unmapped_command_fails_loudly(self) -> None:
        """Mejor un KeyError en el test que un comando sin cuota en produccion."""
        limits = UsageLimits(hard_tokens=1, soft_tokens=1, window=timedelta(hours=1))

        with pytest.raises(KeyError):
            limits.limit_for("/todavia-no-existe")  # type: ignore[arg-type]
