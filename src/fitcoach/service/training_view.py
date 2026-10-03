"""Read-only presentation of the authoritative active prescription."""

from datetime import UTC, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup

from fitcoach.domain.constants import Constants
from fitcoach.domain.training_lifecycle import Mesocycle
from fitcoach.repository.conversation_repository import StoredTrainingPlan

_TEXT = Constants.TRAINING_NAVIGATION


def _pack_sections(sections: list[str]) -> list[str]:
    messages: list[str] = []
    current = ""
    for section in sections:
        combined = f"{current}\n\n{section}" if current else section
        if (
            current
            and len(combined.encode("utf-16-le")) // 2 > Constants.TELEGRAM_MAX_MESSAGE_CHARS
        ):
            messages.append(current)
            current = section
        else:
            current = combined
    if current:
        messages.append(current)
    return messages


def current_week(cycle: Mesocycle | None, now: datetime) -> tuple[int | None, str]:
    if cycle and cycle.completed_at:
        return 4, _TEXT["closed"]
    if cycle is None or cycle.started_at is None:
        return None, _TEXT["unknown"]
    start = cycle.started_at.astimezone(UTC)
    days = (now.astimezone(UTC).date() - start.date()).days
    if days < 0:
        return 1, _TEXT["future"].format(date=start.date())
    if days >= 28:
        return 4, _TEXT["ended"]
    week = days // 7 + 1
    return week, _TEXT["calendar"].format(week=week)


def view_plan(
    stored: StoredTrainingPlan,
    cycle: Mesocycle | None,
    now: datetime,
    *,
    mode: str = "home",
    week: int | None = None,
) -> list[str]:
    plan = stored.plan
    calendar_week, status = current_week(cycle, now)
    if week is not None:
        status = _TEXT["manual"].format(week=week)
    selected = week if week is not None else calendar_week
    lines = [
        _TEXT["week_title"] if mode == "week" else _TEXT["title"].format(version=stored.version),
        f"{Constants.TRAINING_GOAL_LABELS[plan.goal]} · {Constants.TRAINING_ENVIRONMENT_LABELS[plan.environment]}",
        Constants.TRAINING_PREVIEW["schedule"].format(
            days=plan.days_per_week,
            minutes=max(day.estimated_minutes for block in plan.weeks for day in block.days),
        ),
        "",
        status,
    ]
    if plan.excluded_by_injury:
        lines.extend(["", Constants.TRAINING_PREVIEW["restrictions"], *plan.excluded_by_injury])
    if mode == "week" and selected is not None:
        block = plan.weeks[selected - 1]
        lines.extend([
            "",
            Constants.TRAINING_PREVIEW["full_week"].format(
                week=block.week, intensity=Constants.TRAINING_INTENSITY_LABELS[block.intensity]
            ),
        ])
        result = ["\n".join(lines)]
        for day in block.days:
            session = [
                Constants.TRAINING_PREVIEW["day"].format(
                    day=day.day, focus=day.focus, minutes=day.estimated_minutes
                ),
            ]
            for item in day.exercises:
                session.append(
                    Constants.TRAINING_PREVIEW["prescription"].format(
                        name=item.name,
                        sets=item.sets,
                        reps=item.reps,
                        rest=item.rest_seconds,
                        rpe=Constants.TRAINING_PREVIEW["exercise_rpe"].format(value=item.rpe)
                        if item.rpe is not None
                        else "",
                    )
                )
                if item.notes:
                    session.append(Constants.TRAINING_PREVIEW["notes"].format(notes=item.notes))
            result.append("\n".join(session))
        return _pack_sections(result)
    lines.extend([
        "",
        *[
            Constants.TRAINING_PREVIEW["full_week"].format(
                week=block.week, intensity=Constants.TRAINING_INTENSITY_LABELS[block.intensity]
            )
            for block in plan.weeks
        ],
        "",
        _TEXT["choose"],
    ])
    return ["\n".join(lines)]


def view_keyboard(plan_id: int, *, pending: bool = False) -> InlineKeyboardMarkup:
    def button(key: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(_TEXT[key], callback_data=f"tv:{plan_id}:{action}")

    rows = [
        [button("week", "current")],
        [
            InlineKeyboardButton(
                Constants.TRAINING_SWAP_WEEK_BUTTON.format(week=week),
                callback_data=f"tv:{plan_id}:week:{week}",
            )
            for week in range(1, 5)
        ],
        [button("plan", "home"), button("swap", "swap")],
        [button("notes", "notes")],
        [button("review", "review")],
    ]
    if pending:
        rows.append([button("resume", "resume")])
    return InlineKeyboardMarkup(rows)


def persistent_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[_TEXT["week"], _TEXT["plan"]], [_TEXT["swap"], _TEXT["review"]]],
        resize_keyboard=True,
        is_persistent=True,
    )
