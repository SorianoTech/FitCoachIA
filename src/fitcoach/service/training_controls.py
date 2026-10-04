"""Inline controls carry proposal identity and revision, never model-generated actions."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from fitcoach.domain.constants import Constants
from fitcoach.domain.training_lifecycle import TrainingWorkflow


def training_keyboard(
    workflow: TrainingWorkflow, responses: list[str]
) -> InlineKeyboardMarkup | None:
    if any(
        item in responses
        for item in (
            Constants.TRAINING_CONFLICT_MESSAGE,
            Constants.TRAINING_CANCELLED_MESSAGE,
            Constants.TRAINING_CALLBACK_INVALID,
        )
    ):
        return None
    prefix = f"{workflow.id}:{workflow.revision}"

    def button(label: str, action: str, value: str = "") -> InlineKeyboardButton:
        data = f"tr:{action}:{prefix}" + (f":{value}" if value else "")
        return InlineKeyboardButton(label, callback_data=data)

    if workflow.answers.get("date_request") == "input":
        return InlineKeyboardMarkup([[button(Constants.TRAINING_BUTTONS["cancel"], "cancel")]])
    if workflow.answers.get("date_request") == "choose":
        return InlineKeyboardMarkup([
            [
                button(Constants.TRAINING_BUTTONS["tomorrow"], "date", "tomorrow"),
                button(Constants.TRAINING_BUTTONS["monday"], "date", "monday"),
            ],
            [button(Constants.TRAINING_BUTTONS["other"], "date", "other")],
            [button(Constants.TRAINING_BUTTONS["cancel"], "cancel")],
        ])
    if workflow.state == "awaiting_confirmation":
        if workflow.draft is None:
            return InlineKeyboardMarkup(
                [
                    [button(option.exercise.name[:50], "select", str(index))]
                    for index, option in enumerate(workflow.options, 1)
                ]
                + [[button(Constants.TRAINING_BUTTONS["cancel"], "cancel")]]
            )
        rows = [
            [
                button(
                    Constants.TRAINING_BUTTONS["start"]
                    if workflow.kind == "renewal"
                    else Constants.TRAINING_BUTTONS["apply"],
                    "accept",
                )
            ]
        ]
        if workflow.kind == "renewal":
            rows.append([button(Constants.TRAINING_BUTTONS["date"], "dates")])
        rows.extend([
            [button(Constants.TRAINING_BUTTONS["details"], "details")],
            [button(Constants.TRAINING_BUTTONS["swap"], "swap")],
            [button(Constants.TRAINING_BUTTONS["cancel"], "cancel")],
        ])
        return InlineKeyboardMarkup(rows)
    if any(
        text in responses
        for text in (Constants.TRAINING_CLOSURE_QUESTION, Constants.TRAINING_REVIEW_CHOICE)
    ):
        rows = [
            [
                button(
                    Constants.TRAINING_REVIEW_BUTTONS[
                        "good"
                        if Constants.TRAINING_CLOSURE_QUESTION in responses
                        else "closed_good"
                    ],
                    "good",
                )
            ],
            [
                button(
                    Constants.TRAINING_REVIEW_BUTTONS[
                        "changes"
                        if Constants.TRAINING_CLOSURE_QUESTION in responses
                        else "closed_changes"
                    ],
                    "changes",
                )
            ],
        ]
        if Constants.TRAINING_CLOSURE_QUESTION in responses:
            rows.append([button(Constants.TRAINING_BUTTONS["not_yet"], "postpone")])
        return InlineKeyboardMarkup(rows)
    return None
