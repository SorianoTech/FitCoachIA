import pytest

from fitcoach.service.exercise_submission_controls import (
    exercise_submission_keyboard,
    parse_exercise_submission_callback,
)


def test_keyboard_contains_confirm_and_cancel_actions_for_submission() -> None:
    keyboard = exercise_submission_keyboard(42)

    assert [button.text for button in keyboard.inline_keyboard[0]] == ["Confirmar", "Cancelar"]
    assert [button.callback_data for button in keyboard.inline_keyboard[0]] == [
        "ex:confirm:42",
        "ex:cancel:42",
    ]
    assert all(
        len(button.callback_data.encode()) <= 64
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data is not None
    )


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("ex:confirm:42", ("confirm", 42)),
        ("ex:cancel:7", ("cancel", 7)),
        ("ex:confirm:0", None),
        ("ex:confirm:-1", None),
        ("ex:confirm:not-an-id", None),
        ("ex:unknown:42", None),
        ("tr:confirm:42", None),
    ],
)
def test_callback_parser_accepts_only_known_positive_actions(
    data: str,
    expected: tuple[str, int] | None,
) -> None:
    assert parse_exercise_submission_callback(data) == expected
