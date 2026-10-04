"""Inline controls carry proposal identity and revision, never model-generated actions."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from fitcoach.domain.constants import Constants
from fitcoach.domain.trainer_plan import TrainingPlan
from fitcoach.domain.training_lifecycle import TrainingWorkflow


def training_keyboard(
    workflow: TrainingWorkflow, responses: list[str], plan: TrainingPlan | None = None
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

    if workflow.answers.get("swap_clarification") or workflow.answers.get("safety_hold"):
        return InlineKeyboardMarkup([[button(Constants.TRAINING_BUTTONS["cancel"], "cancel")]])
    if workflow.state == "reviewing" and workflow.answers.get("swap_step") and plan:
        step = workflow.answers["swap_step"]
        rows = []
        if step == "exercise":
            exercises: dict[int, tuple[int, str]] = {}
            for week in plan.weeks:
                if (
                    workflow.answers.get("swap_filter_week")
                    and str(week.week) != workflow.answers["swap_filter_week"]
                ):
                    continue
                for day in week.days:
                    for item in day.exercises:
                        if (
                            workflow.answers.get("swap_filter_exercise")
                            and str(item.exercise_id) != workflow.answers["swap_filter_exercise"]
                        ):
                            continue
                        exercises.setdefault(item.exercise_id, (day.day, item.name))
            page = int(workflow.answers.get("swap_page", "0"))
            items = list(exercises.items())
            for exercise_id, (day_number, name) in items[page * 8 : (page + 1) * 8]:
                rows.append([
                    button(
                        Constants.TRAINING_SWAP_DAY_BUTTON.format(day=day_number, name=name[:45]),
                        "exercise",
                        str(exercise_id),
                    )
                ])
            navigation = []
            if page:
                navigation.append(
                    button(Constants.TRAINING_SWAP_NAVIGATION["previous"], "page", str(page - 1))
                )
            if (page + 1) * 8 < len(items):
                navigation.append(
                    button(Constants.TRAINING_SWAP_NAVIGATION["next"], "page", str(page + 1))
                )
            if navigation:
                rows.append(navigation)
        elif step == "week":
            exercise_id = int(workflow.answers["swap_exercise"])
            rows = [
                [
                    button(
                        Constants.TRAINING_SWAP_WEEK_BUTTON.format(week=week.week),
                        "week",
                        str(week.week),
                    )
                ]
                for week in plan.weeks
                if any(
                    item.exercise_id == exercise_id for day in week.days for item in day.exercises
                )
            ]
        elif step == "reason":
            rows = [
                [button(label, "reason", value)]
                for value, label in Constants.TRAINING_SWAP_REASONS.items()
            ]
        rows.append([button(Constants.TRAINING_BUTTONS["cancel"], "cancel")])
        return InlineKeyboardMarkup(rows)
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
