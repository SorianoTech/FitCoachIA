"""Render the validated prescription, not a second model-generated summary."""

from fitcoach.domain.constants import Constants
from fitcoach.domain.training_lifecycle import TrainingWorkflow

_TEXT = Constants.TRAINING_PREVIEW


def _line(value: str, limit: int = 100) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else normalized[: limit - 1] + "…"


def preview(workflow: TrainingWorkflow) -> str:
    plan = workflow.draft
    if plan is None:
        raise ValueError("A preview requires a validated draft")
    lines = [
        _TEXT["renewal"] if workflow.kind == "renewal" else _TEXT["swap"],
        _TEXT["pending"],
        "",
        f"{Constants.TRAINING_GOAL_LABELS[plan.goal]} · {Constants.TRAINING_ENVIRONMENT_LABELS[plan.environment]}",
        _TEXT["schedule"].format(
            days=plan.days_per_week,
            minutes=max(day.estimated_minutes for week in plan.weeks for day in week.days),
        ),
        "",
    ]
    profile = workflow.effective_profile
    restrictions = list(plan.excluded_by_injury)
    if profile:
        restrictions.extend(f"{item.location}: {item.restriction}" for item in profile.injuries)
        if profile.flags.red:
            restrictions.insert(0, _TEXT["flags"].format(flags=", ".join(profile.flags.red)))
    if restrictions:
        lines.append(_TEXT["restrictions"])
        lines.extend(f"• {_line(item, 180)}" for item in dict.fromkeys(restrictions))
        lines.append("")
    if workflow.kind == "exercise_swap" and workflow.swap:
        lines.extend([
            _TEXT["swap_scope"].format(id=workflow.swap.exercise_id, week=workflow.swap.from_week),
            "",
        ])
        selected = workflow.answers.get("selected_exercise_id")
        options = [
            option for option in workflow.options if str(option.exercise.exercise_id) == selected
        ]
        if not selected:
            # Old persisted drafts predate the explicit selection marker.
            candidates = [
                option
                for option in workflow.options
                if option.exercise.exercise_id in plan.exercise_ids()
            ]
            options = candidates if len(candidates) == 1 else []
        if not options and workflow.report:
            lines.extend([_line(workflow.report, 300), ""])
        for option in options:
            item = next(
                item
                for week in plan.weeks
                if week.week >= workflow.swap.from_week
                for day in week.days
                for item in day.exercises
                if item.exercise_id == option.exercise.exercise_id
            )
            lines.append(
                _TEXT["prescription"].format(
                    name=_line(item.name),
                    sets=item.sets,
                    reps=_line(item.reps, 30),
                    rest=item.rest_seconds,
                    rpe=_TEXT["exercise_rpe"].format(value=item.rpe) if item.rpe else "",
                )
            )
            lines.extend([_line(option.rationale, 180), ""])
    else:
        lines.append(_TEXT["sessions"])
        for day in plan.weeks[0].days:
            lines.append(
                _TEXT["day"].format(
                    day=day.day, focus=_line(day.focus, 45), minutes=day.estimated_minutes
                )
            )
            for item in day.exercises[:3]:
                lines.append(f"  • {_line(item.name, 55)} · {item.sets} × {_line(item.reps, 20)}")
            if len(day.exercises) > 3:
                lines.append(_TEXT["more"].format(count=len(day.exercises) - 3))
            lines.append("")
    lines.append(_TEXT["progression"])
    for week in plan.weeks:
        items = [item for day in week.days for item in day.exercises]
        rpes = [item.rpe for item in items if item.rpe is not None]
        lines.append(
            _TEXT["week"].format(
                week=week.week,
                intensity=Constants.TRAINING_INTENSITY_LABELS[week.intensity],
                sets=sum(item.sets for item in items),
                rpe=_TEXT["rpe"].format(value=max(rpes)) if rpes else "",
            )
        )
    lines.extend([_TEXT["sets_note"], ""])
    body = "\n".join(lines)
    # Keep buttons on one compact message even for maximal seven-day plans.
    if len(body.encode("utf-16-le")) // 2 > 3500:
        compact = []
        size = 0
        for line in lines:
            size += len(line.encode("utf-16-le")) // 2 + 1
            if size > 3300:
                break
            compact.append(line)
        body = "\n".join([*compact, _TEXT["truncated"]])
    return body + "\n" + _TEXT["footer"]


def details(workflow: TrainingWorkflow) -> list[str]:
    plan = workflow.draft
    if plan is None:
        raise ValueError("Details require a validated draft")
    result = [_TEXT["full"]]
    for week in plan.weeks:
        lines = [
            _TEXT["full_week"].format(
                week=week.week, intensity=Constants.TRAINING_INTENSITY_LABELS[week.intensity]
            ),
            "",
        ]
        for day in week.days:
            lines.append(
                _TEXT["day"].format(day=day.day, focus=day.focus, minutes=day.estimated_minutes)
            )
            for item in day.exercises:
                lines.append(
                    _TEXT["prescription"].format(
                        name=item.name,
                        sets=item.sets,
                        reps=item.reps,
                        rest=item.rest_seconds,
                        rpe=_TEXT["exercise_rpe"].format(value=item.rpe) if item.rpe else "",
                    )
                )
                if item.notes:
                    lines.append(_TEXT["notes"].format(notes=item.notes))
            lines.append("")
        result.append("\n".join(lines))
    result.append(_TEXT["progression_notes"] + "\n" + plan.progression_notes)
    if workflow.report:
        result.append(_TEXT["report"] + "\n" + workflow.report)
    if workflow.answers.get("interpretation"):
        result.append(_TEXT["review"] + "\n" + workflow.answers["interpretation"])
    profile = workflow.effective_profile
    if profile:
        result.append(
            _TEXT["profile"]
            + "\n"
            + Constants.TRAINING_MESSAGES["context"].format(
                goal=Constants.TRAINING_GOAL_LABELS[profile.goal.primary],
                days=profile.commitment.days_per_week,
                minutes=profile.commitment.minutes_per_session,
                environment=Constants.TRAINING_ENVIRONMENT_LABELS[profile.training.environment],
                equipment=", ".join(profile.training.equipment),
                sleep=profile.sleep.average_hours,
                injuries="; ".join(
                    f"{item.location}: {item.restriction}" for item in profile.injuries
                )
                or Constants.TRAINING_MESSAGES["no_injuries"],
            )
        )
    return [*result, preview(workflow)]
