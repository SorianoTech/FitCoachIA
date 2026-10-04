"""Inline controls for confirming or cancelling an exercise proposal."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from fitcoach.domain.constants import Constants
from fitcoach.domain.exercise_submission import ExerciseSubmissionAction

_CALLBACK_PREFIX = "ex"


def exercise_submission_keyboard(submission_id: int) -> InlineKeyboardMarkup:
    def button(label: str, action: ExerciseSubmissionAction) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            label,
            callback_data=f"{_CALLBACK_PREFIX}:{action}:{submission_id}",
        )

    return InlineKeyboardMarkup([
        [
            button(Constants.EXERCISE_SUBMISSION_BUTTONS["confirm"], "confirm"),
            button(Constants.EXERCISE_SUBMISSION_BUTTONS["cancel"], "cancel"),
        ]
    ])


def parse_exercise_submission_callback(
    data: str,
) -> tuple[ExerciseSubmissionAction, int] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != _CALLBACK_PREFIX:
        return None
    action: ExerciseSubmissionAction
    if parts[1] == "confirm":
        action = "confirm"
    elif parts[1] == "cancel":
        action = "cancel"
    else:
        return None
    try:
        submission_id = int(parts[2])
    except ValueError:
        return None
    if submission_id <= 0:
        return None
    return action, submission_id
