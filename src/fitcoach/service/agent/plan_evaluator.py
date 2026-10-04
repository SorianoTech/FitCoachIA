"""Deterministic checks of a generated plan against the trainer skill's rules.

Pydantic guarantees the plan's *shape*; this module checks what the skill asks
for and the schema cannot express: time budget, weekly volume, periodization,
RPE caps, injuries, red flags... Every rule returns findings instead of raising,
so a plan can be scored and two prompt variants compared on the same cases.

``error`` findings break an explicit rule of the skill; ``warning`` findings are
heuristics (keyword matching, approximate time formula) worth a human look;
``info`` findings describe the catalogue, to tell a prompt problem apart from a
retrieval problem (no prompt can program a back exercise the catalogue lacks).
"""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from fitcoach.domain.exercise import Exercise
from fitcoach.domain.exercise_catalogue import (
    MUSCLE_TARGETS,
    available_equipment,
    normalize_equipment,
)
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.trainer_plan import (
    RPE_CAPS,
    PlannedExercise,
    TrainerTurn,
    TrainingPlan,
    TrainingWeek,
)

TELEGRAM_MAX_MESSAGE_CHARS = 4096
REPLY_SOFT_LIMIT_CHARS = 600
WARMUP_MINUTES = 8
COOLDOWN_MINUTES = 5
WORKING_SECONDS_PER_SET = 40
# The formula is an estimate: only flag sessions clearly over the client's budget.
TIME_FORMULA_TOLERANCE = 1.15
DELOAD_RANGE = (0.4, 0.7)
ERROR_PENALTY = 15
WARNING_PENALTY = 3

# Skill table "Rep ranges and rest by goal", widened slightly to absorb accessories.
GOAL_REPS = {"lose_fat": (8, 20), "gain_muscle": (5, 15), "performance": (1, 10)}
GOAL_REST = {"lose_fat": (30, 90), "gain_muscle": (60, 240), "performance": (90, 300)}

# Exercise ``target`` values in the corpus, grouped the way a split talks about them.
MUSCLE_GROUPS = MUSCLE_TARGETS
ESSENTIAL_GROUPS = ("chest", "back", "legs")

# Injury location keywords -> exercise-name patterns that usually conflict with it.
INJURY_PATTERNS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("rodilla", "knee", "menisco", "rotul", "ligamento cruzado"),
        ("squat", "lunge", "jump", "burpee", "run", "pistol", "split", "sprint", "hop", "skater"),
    ),
    (
        ("hombro", "shoulder", "manguito", "rotator", "supraespinoso"),
        (
            "overhead",
            "military",
            "shoulder press",
            "push press",
            "snatch",
            "jerk",
            "thruster",
            "handstand",
            "behind neck",
            "upright row",
            "clean and press",
        ),
    ),
    (
        ("lumbar", "espalda baja", "lower back", "hernia", "disc"),
        ("deadlift", "good morning", "back extension", "hyperextension", "clean", "snatch"),
    ),
    (
        ("muñeca", "muneca", "wrist"),
        ("push-up", "push up", "planche", "handstand", "front lever"),
    ),
)
REFERRAL_KEYWORDS = (
    "profesional",
    "médic",
    "medic",
    "doctor",
    "fisioterapeut",
    "cardiólog",
    "cardiolog",
    "professional",
    "physician",
)
_NUMBER = re.compile(r"\d+")
_TIME_REPS = re.compile(r"\d+\s*(s|seg|sec|min)\b|\b(seg|segundos|seconds|min|minutos)\b")


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    severity: Severity
    message: str
    where: str = ""


@dataclass(slots=True)
class PlanEvaluation:
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def count(self, severity: Severity) -> int:
        return sum(1 for finding in self.findings if finding.severity is severity)

    @property
    def errors(self) -> int:
        return self.count(Severity.ERROR)

    @property
    def warnings(self) -> int:
        return self.count(Severity.WARNING)

    @property
    def passed(self) -> bool:
        return self.errors == 0

    @property
    def score(self) -> int:
        return max(0, 100 - ERROR_PENALTY * self.errors - WARNING_PENALTY * self.warnings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "metrics": self.metrics,
            "findings": [asdict(finding) for finding in self.findings],
        }


def evaluate_turn(
    turn: TrainerTurn, profile: InterviewerProfile, catalogue: Sequence[Exercise]
) -> PlanEvaluation:
    evaluation = PlanEvaluation()
    _check_messages(evaluation, turn, profile)
    if turn.plan is None:
        _check_catalogue(evaluation, catalogue)
        evaluation.findings.append(
            Finding("no_plan", Severity.ERROR, f"The turn is '{turn.status}', not a plan")
        )
        return evaluation
    evaluate_plan(turn.plan, profile, catalogue, evaluation)
    _check_referral(evaluation, turn, profile)
    return evaluation


def evaluate_plan(
    plan: TrainingPlan,
    profile: InterviewerProfile,
    catalogue: Sequence[Exercise],
    evaluation: PlanEvaluation | None = None,
) -> PlanEvaluation:
    evaluation = evaluation or PlanEvaluation()
    _check_catalogue(evaluation, catalogue)
    by_id = {exercise.id: exercise for exercise in catalogue}
    checks = (
        _check_profile_echo,
        _check_names,
        _check_equipment,
        _check_days,
        _check_volume,
        _check_periodization,
        _check_rpe,
        _check_goal_ranges,
        _check_consistency,
        _check_coverage,
        _check_injuries,
        _check_red_flags,
    )
    for check in checks:
        check(evaluation, plan, profile, by_id)
    evaluation.metrics.update(_metrics(plan, profile, by_id))
    return evaluation


def evaluate_constraints(
    plan: TrainingPlan, profile: InterviewerProfile, catalogue: Sequence[Exercise]
) -> PlanEvaluation:
    """Only exact identity, availability, profile and declared session constraints."""
    evaluation = PlanEvaluation()
    by_id = {exercise.id: exercise for exercise in catalogue}
    for check in (_check_profile_echo, _check_names, _check_equipment, _check_days):
        check(evaluation, plan, profile, by_id)
    return evaluation


def _check_equipment(
    evaluation: PlanEvaluation,
    plan: TrainingPlan,
    profile: InterviewerProfile,
    by_id: dict[int, Exercise],
) -> None:
    available = available_equipment(profile.training.equipment)
    for where, item in _exercises(plan):
        exercise = by_id.get(item.exercise_id)
        if exercise is not None and (
            not exercise.equipment or normalize_equipment(exercise.equipment) not in available
        ):
            _add(
                evaluation,
                "unavailable_equipment",
                Severity.ERROR,
                f"Exercise {item.exercise_id} requires unconfirmed equipment",
                where,
            )


def _add(
    evaluation: PlanEvaluation, rule: str, severity: Severity, message: str, where: str = ""
) -> None:
    evaluation.findings.append(Finding(rule, severity, message, where))


def _check_catalogue(evaluation: PlanEvaluation, catalogue: Sequence[Exercise]) -> None:
    available = _groups_of(catalogue)
    evaluation.metrics["catalogue_size"] = len(catalogue)
    evaluation.metrics["catalogue_groups"] = dict(sorted(Counter(available).items()))
    for group in MUSCLE_GROUPS:
        if group not in available:
            _add(
                evaluation,
                "catalogue_missing_group",
                Severity.INFO,
                f"The retrieved catalogue has no '{group}' exercise (retrieval, not prompt)",
            )


def _check_messages(
    evaluation: PlanEvaluation, turn: TrainerTurn, profile: InterviewerProfile
) -> None:
    if len(turn.reply) > REPLY_SOFT_LIMIT_CHARS:
        _add(
            evaluation,
            "reply_too_long",
            Severity.WARNING,
            f"reply has {len(turn.reply)} chars; it should be a short Telegram message",
        )
    if turn.report is not None and len(turn.report) > TELEGRAM_MAX_MESSAGE_CHARS:
        _add(
            evaluation,
            "report_over_telegram_limit",
            Severity.ERROR,
            f"report has {len(turn.report)} chars; Telegram rejects more than "
            f"{TELEGRAM_MAX_MESSAGE_CHARS}",
        )


def _check_profile_echo(
    evaluation: PlanEvaluation,
    plan: TrainingPlan,
    profile: InterviewerProfile,
    by_id: dict[int, Exercise],
) -> None:
    expected = {
        "goal": profile.goal.primary,
        "environment": profile.training.environment,
        "days_per_week": profile.commitment.days_per_week,
    }
    for name, value in expected.items():
        actual = getattr(plan, name)
        if actual != value:
            _add(
                evaluation,
                "profile_mismatch",
                Severity.ERROR,
                f"plan.{name}={actual!r} but the profile says {value!r}",
            )


def _check_names(
    evaluation: PlanEvaluation,
    plan: TrainingPlan,
    profile: InterviewerProfile,
    by_id: dict[int, Exercise],
) -> None:
    for where, exercise in _exercises(plan):
        known = by_id.get(exercise.exercise_id)
        if known is None:
            _add(
                evaluation,
                "unknown_exercise_id",
                Severity.ERROR,
                f"exercise_id {exercise.exercise_id} is not in the catalogue",
                where,
            )
        elif known.name.strip().lower() != exercise.name.strip().lower():
            _add(
                evaluation,
                "name_mismatch",
                Severity.ERROR,
                f"id {exercise.exercise_id} is '{known.name}' in the catalogue, "
                f"not '{exercise.name}'",
                where,
            )


def _check_days(
    evaluation: PlanEvaluation,
    plan: TrainingPlan,
    profile: InterviewerProfile,
    by_id: dict[int, Exercise],
) -> None:
    budget = profile.commitment.minutes_per_session
    for week in plan.weeks:
        for day in week.days:
            where = f"W{week.week}D{day.day}"
            if day.estimated_minutes > budget:
                _add(
                    evaluation,
                    "session_over_budget",
                    Severity.ERROR,
                    f"estimated_minutes={day.estimated_minutes} > minutes_per_session={budget}",
                    where,
                )
            formula = estimate_session_minutes(day.exercises)
            if formula > budget * TIME_FORMULA_TOLERANCE:
                _add(
                    evaluation,
                    "session_time_formula_over_budget",
                    Severity.WARNING,
                    f"the skill's time formula gives ~{formula:.0f} min for a {budget} min budget "
                    f"(declared {day.estimated_minutes})",
                    where,
                )
            ids = [exercise.exercise_id for exercise in day.exercises]
            repeated = sorted(id_ for id_, count in Counter(ids).items() if count > 1)
            if repeated:
                _add(
                    evaluation,
                    "duplicate_exercise_in_day",
                    Severity.ERROR,
                    f"exercise ids repeated in the same day: {repeated}",
                    where,
                )


def _check_volume(
    evaluation: PlanEvaluation,
    plan: TrainingPlan,
    profile: InterviewerProfile,
    by_id: dict[int, Exercise],
) -> None:
    """``tolerable_volume_sets`` is sets per muscle group per week (interviewer skill)."""
    ceiling = profile.initial_calculations.tolerable_volume_sets
    weeks = plan.weeks if profile.flags.red else plan.weeks[:1]
    for week in weeks:
        for target, sets in _sets_per_target(week, by_id).items():
            if sets > ceiling:
                _add(
                    evaluation,
                    "volume_over_ceiling",
                    Severity.ERROR,
                    f"{sets} weekly sets for '{target}' > tolerable_volume_sets={ceiling}",
                    f"W{week.week}",
                )


def _check_periodization(
    evaluation: PlanEvaluation,
    plan: TrainingPlan,
    profile: InterviewerProfile,
    by_id: dict[int, Exercise],
) -> None:
    sets = [_weekly_sets(week) for week in plan.weeks]
    rpe = [_mean_rpe(week) for week in plan.weeks]
    for previous, current in ((0, 1), (1, 2)):
        previous_rpe, current_rpe = rpe[previous], rpe[current]
        harder = previous_rpe is not None and current_rpe is not None and current_rpe > previous_rpe
        if sets[current] < sets[previous] or (sets[current] == sets[previous] and not harder):
            _add(
                evaluation,
                "no_progression",
                Severity.WARNING,
                f"week {current + 1} ({sets[current]} sets, rpe {rpe[current]}) does not add "
                f"stimulus over week {previous + 1} ({sets[previous]} sets, rpe {rpe[previous]})",
                f"W{current + 1}",
            )
    if sets[0]:
        ratio = sets[3] / sets[0]
        low, high = DELOAD_RANGE
        if ratio >= 1:
            severity = Severity.ERROR
        elif not low <= ratio <= high:
            severity = Severity.WARNING
        else:
            return
        _add(
            evaluation,
            "deload_volume",
            severity,
            f"deload has {sets[3]} sets, {ratio:.0%} of week 1 (expected 50-60%)",
            "W4",
        )


def _check_rpe(
    evaluation: PlanEvaluation,
    plan: TrainingPlan,
    profile: InterviewerProfile,
    by_id: dict[int, Exercise],
) -> None:
    for week in plan.weeks:
        cap = RPE_CAPS.get(week.week)
        if cap is None:
            continue
        values = [ex.rpe for day in week.days for ex in day.exercises if ex.rpe is not None]
        if values and max(values) > cap:
            _add(
                evaluation,
                "rpe_over_cap",
                Severity.ERROR,
                f"max rpe {max(values):g} > {cap:g} allowed in week {week.week}",
                f"W{week.week}",
            )


def _check_goal_ranges(
    evaluation: PlanEvaluation,
    plan: TrainingPlan,
    profile: InterviewerProfile,
    by_id: dict[int, Exercise],
) -> None:
    rep_low, rep_high = GOAL_REPS[plan.goal]
    rest_low, rest_high = GOAL_REST[plan.goal]
    off_reps: list[str] = []
    off_rest: list[str] = []
    for where, exercise in _exercises(plan.weeks[0:1]):
        reps = _rep_bounds(exercise.reps)
        if reps is not None and (reps[1] < rep_low or reps[0] > rep_high):
            off_reps.append(f"{where} {exercise.name} ({exercise.reps})")
        if not rest_low <= exercise.rest_seconds <= rest_high:
            off_rest.append(f"{where} {exercise.name} ({exercise.rest_seconds}s)")
    if off_reps:
        _add(
            evaluation,
            "reps_outside_goal_range",
            Severity.WARNING,
            f"{len(off_reps)} exercise(s) outside {rep_low}-{rep_high} reps for "
            f"{plan.goal}: {off_reps[:5]}",
            "W1",
        )
    if off_rest:
        _add(
            evaluation,
            "rest_outside_goal_range",
            Severity.WARNING,
            f"{len(off_rest)} exercise(s) outside {rest_low}-{rest_high}s rest for "
            f"{plan.goal}: {off_rest[:5]}",
            "W1",
        )


def _check_consistency(
    evaluation: PlanEvaluation,
    plan: TrainingPlan,
    profile: InterviewerProfile,
    by_id: dict[int, Exercise],
) -> None:
    """Weeks 1-3 should keep the same core exercises so progression is measurable."""
    base = {day.day: {ex.exercise_id for ex in day.exercises} for day in plan.weeks[0].days}
    for week in plan.weeks[1:3]:
        for day in week.days:
            reference = base.get(day.day)
            current = {ex.exercise_id for ex in day.exercises}
            if reference and len(reference & current) / len(reference) < 0.5:
                _add(
                    evaluation,
                    "exercises_change_between_weeks",
                    Severity.WARNING,
                    "less than half of week 1's exercises are kept, progression is not measurable",
                    f"W{week.week}D{day.day}",
                )


def _check_coverage(
    evaluation: PlanEvaluation,
    plan: TrainingPlan,
    profile: InterviewerProfile,
    by_id: dict[int, Exercise],
) -> None:
    trained = _groups_of(
        by_id[ex.exercise_id] for _, ex in _exercises(plan.weeks[0:1]) if ex.exercise_id in by_id
    )
    available = _groups_of(by_id.values())
    for group in ESSENTIAL_GROUPS:
        if group in trained:
            continue
        if group in available:
            _add(
                evaluation,
                "group_not_trained",
                Severity.WARNING,
                f"week 1 has no '{group}' exercise although the catalogue offers one",
                "W1",
            )
        else:
            _add(
                evaluation,
                "group_not_trained",
                Severity.INFO,
                f"week 1 has no '{group}' exercise; the catalogue has none either",
                "W1",
            )


def _check_injuries(
    evaluation: PlanEvaluation,
    plan: TrainingPlan,
    profile: InterviewerProfile,
    by_id: dict[int, Exercise],
) -> None:
    if profile.injuries and not plan.excluded_by_injury:
        _add(
            evaluation,
            "injury_not_recorded",
            Severity.ERROR,
            f"the profile reports {len(profile.injuries)} injury(ies) but excluded_by_injury "
            "is empty",
        )
    if not profile.injuries and plan.excluded_by_injury:
        _add(
            evaluation,
            "phantom_injury_exclusion",
            Severity.WARNING,
            "excluded_by_injury is not empty but the profile reports no injury",
        )
    for injury in profile.injuries:
        injury_text = f"{injury.location} {injury.type} {injury.restriction}".lower()
        patterns = [
            pattern
            for keywords, names in INJURY_PATTERNS
            if any(keyword in injury_text for keyword in keywords)
            for pattern in names
        ]
        conflicts = sorted({
            f"{where} {ex.name}"
            for where, ex in _exercises(plan)
            if any(pattern in ex.name.lower() for pattern in patterns)
        })
        if conflicts:
            _add(
                evaluation,
                "possible_injury_conflict",
                Severity.WARNING,
                f"'{injury.location}' ({injury.restriction}) may conflict with: {conflicts[:6]}",
            )


def _check_red_flags(
    evaluation: PlanEvaluation,
    plan: TrainingPlan,
    profile: InterviewerProfile,
    by_id: dict[int, Exercise],
) -> None:
    if not profile.flags.red:
        return
    maximal = [f"{where} {ex.name}" for where, ex in _exercises(plan) if ex.rpe and ex.rpe >= 9]
    if maximal:
        _add(
            evaluation,
            "red_flags_maximal_effort",
            Severity.ERROR,
            f"red flags present but rpe >= 9 is programmed: {maximal[:5]}",
        )


def _check_referral(
    evaluation: PlanEvaluation, turn: TrainerTurn, profile: InterviewerProfile
) -> None:
    if profile.flags.red and not _mentions_referral(f"{turn.report or ''} {turn.reply}"):
        _add(
            evaluation,
            "red_flags_no_referral",
            Severity.ERROR,
            "red flags present but the report does not refer the client to a professional",
        )


def _mentions_referral(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in REFERRAL_KEYWORDS)


def _metrics(
    plan: TrainingPlan, profile: InterviewerProfile, by_id: dict[int, Exercise]
) -> dict[str, Any]:
    week1_targets = _sets_per_target(plan.weeks[0], by_id)
    days = [day for week in plan.weeks for day in week.days]
    return {
        "weekly_sets": [_weekly_sets(week) for week in plan.weeks],
        "mean_rpe": [_mean_rpe(week) for week in plan.weeks],
        "week1_sets_per_target": dict(sorted(week1_targets.items())),
        "tolerable_volume_sets": profile.initial_calculations.tolerable_volume_sets,
        "max_estimated_minutes": max(day.estimated_minutes for day in days),
        "max_formula_minutes": round(max(estimate_session_minutes(day.exercises) for day in days)),
        "minutes_per_session": profile.commitment.minutes_per_session,
        "exercises_per_day": round(sum(len(day.exercises) for day in days) / len(days), 1),
        "distinct_exercises": len(plan.exercise_ids()),
    }


def _exercises(
    plan_or_weeks: TrainingPlan | Sequence[TrainingWeek],
) -> Iterable[tuple[str, PlannedExercise]]:
    weeks = plan_or_weeks.weeks if isinstance(plan_or_weeks, TrainingPlan) else plan_or_weeks
    for week in weeks:
        for day in week.days:
            for exercise in day.exercises:
                yield f"W{week.week}D{day.day}", exercise


def _weekly_sets(week: TrainingWeek) -> int:
    return sum(exercise.sets for day in week.days for exercise in day.exercises)


def _mean_rpe(week: TrainingWeek) -> float | None:
    values = [ex.rpe for day in week.days for ex in day.exercises if ex.rpe is not None]
    return round(sum(values) / len(values), 2) if values else None


def _sets_per_target(week: TrainingWeek, by_id: dict[int, Exercise]) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for day in week.days:
        for exercise in day.exercises:
            known = by_id.get(exercise.exercise_id)
            target = (known.target if known and known.target else "unknown").lower()
            totals[target] += exercise.sets
    return dict(totals)


def _groups_of(exercises: Iterable[Exercise]) -> list[str]:
    groups: list[str] = []
    for exercise in exercises:
        target = (exercise.target or "").lower()
        groups.extend(group for group, targets in MUSCLE_GROUPS.items() if target in targets)
    return groups


def estimate_session_minutes(exercises: Sequence[PlannedExercise]) -> float:
    """The skill's formula: warm-up + Σ sets × (work + rest) + cool-down."""
    work = sum(ex.sets * (WORKING_SECONDS_PER_SET + ex.rest_seconds) for ex in exercises)
    return WARMUP_MINUTES + work / 60 + COOLDOWN_MINUTES


def _rep_bounds(reps: str) -> tuple[int, int] | None:
    lowered = reps.lower()
    if _TIME_REPS.search(lowered):
        return None
    numbers = [int(number) for number in _NUMBER.findall(lowered)]
    if not numbers:
        return None
    return min(numbers), max(numbers)
