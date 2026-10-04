from fitcoach.domain.telegram import Commands


def test_command_supports_telegram_bot_suffix() -> None:
    assert Commands.from_value("/approve_exercise@Fitcoachdev_bot") is Commands.APPROVE_EXERCISE


def test_command_suggests_close_known_spelling() -> None:
    assert Commands.suggest("/approve_excercise") == "/approve_exercise"


def test_command_does_not_suggest_unrelated_text() -> None:
    assert Commands.suggest("/completely_unrelated") is None
