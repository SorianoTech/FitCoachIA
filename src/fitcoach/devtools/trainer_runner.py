"""Run the Trainer offline on one profile + catalogue and keep every artifact.

No Telegram, no conversation database: a run is a pure function of
(profile, catalogue, prompt/skill variant, model settings), which is what makes
prompt tuning repeatable. Every run writes what was sent, what came back and
the validated plan, so a bad plan can be traced to the exact prompt that caused it.
"""

import hashlib
import json
import re
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage

from fitcoach.devtools.recording_model import RecordedCall, RecordingChatModel, serialize_message
from fitcoach.domain.agent_errors import AgentError
from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.token_usage import TokenUsage
from fitcoach.domain.trainer_plan import TrainerTurn
from fitcoach.infrastructure.prompts.prompt_loader import PromptLoader
from fitcoach.service.agent.llm_chain import AsyncChatModel
from fitcoach.service.agent.plan_evaluator import PlanEvaluation, Severity, evaluate_turn
from fitcoach.service.agent.trainer_chain import TrainerChain

_SLUG = re.compile(r"[^a-zA-Z0-9_.-]+")


@dataclass(frozen=True, slots=True)
class TrainerVariant:
    """One prompt/skill combination to evaluate. ``None`` roots mean the packaged assets."""

    name: str = "default"
    skill: str = "trainer"
    prompts_root: Path | None = None
    skills_root: Path | None = None

    def loader(self) -> PromptLoader:
        return PromptLoader(self.prompts_root, self.skills_root)


@dataclass(slots=True)
class TrainerRun:
    case: str
    variant: TrainerVariant
    model: str
    prompt_fingerprint: str
    profile: InterviewerProfile
    exercises: list[Exercise]
    calls: list[RecordedCall] = field(default_factory=list)
    turn: TrainerTurn | None = None
    token_usages: list[TokenUsage] = field(default_factory=list)
    error: str | None = None
    latency_ms: int = 0
    evaluation: PlanEvaluation | None = None

    @property
    def status(self) -> str:
        if self.turn is None:
            return "error"
        return self.turn.status.value

    @property
    def repaired(self) -> bool:
        return len(self.calls) > 1

    @property
    def total_tokens(self) -> int:
        return sum(usage.total_tokens for usage in self.token_usages)


class _OfflineModel:
    """Stands in for the provider when only the prompt is rendered."""

    async def ainvoke(self, input: list[BaseMessage]) -> BaseMessage:  # noqa: A002
        raise RuntimeError("render-only: the model must not be called")


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def build_chain(model: AsyncChatModel, model_name: str, variant: TrainerVariant) -> TrainerChain:
    """A fresh chain per run, so edits to the prompt or skill on disk apply immediately."""
    return TrainerChain(model, model_name, skill_name=variant.skill, loader=variant.loader())


def render_messages(
    profile: InterviewerProfile, exercises: Sequence[Exercise], variant: TrainerVariant
) -> list[dict[str, Any]]:
    chain = build_chain(_OfflineModel(), "render-only", variant)
    return [serialize_message(message) for message in chain.plan_messages(profile, exercises)]


async def run_trainer_case(
    case: str,
    profile: InterviewerProfile,
    exercises: Sequence[Exercise],
    model: AsyncChatModel,
    model_name: str,
    variant: TrainerVariant,
) -> TrainerRun:
    recorder = RecordingChatModel(model)
    chain = build_chain(recorder, model_name, variant)
    run = TrainerRun(
        case=case,
        variant=variant,
        model=model_name,
        prompt_fingerprint=fingerprint(chain.system_prompt),
        profile=profile,
        exercises=list(exercises),
        calls=recorder.calls,
    )
    started = time.perf_counter()
    try:
        reply = await chain.generate_plan(profile, exercises)
    except AgentError as exc:
        run.error = exc.code.value
        run.token_usages = list(exc.token_usages)
    except Exception as exc:  # a debugging tool must report, not crash, on any failure
        run.error = f"{type(exc).__name__}: {exc}"
    else:
        run.turn = reply.turn
        run.token_usages = reply.token_usages
        run.evaluation = evaluate_turn(reply.turn, profile, exercises)
    run.latency_ms = int((time.perf_counter() - started) * 1000)
    return run


def evaluate_run_dir(run_dir: Path) -> PlanEvaluation:
    """Re-score a stored run, e.g. after adding a rule, without calling the model again."""
    turn = TrainerTurn.model_validate_json((run_dir / "plan.json").read_text(encoding="utf-8"))
    profile = load_profile(run_dir / "profile.json")
    catalogue = load_catalogue(run_dir / "catalogue.json")
    evaluation = evaluate_turn(turn, profile, catalogue)
    write_evaluation(evaluation, run_dir)
    return evaluation


def write_evaluation(evaluation: PlanEvaluation, out_dir: Path) -> None:
    _write_json(out_dir / "evaluation.json", evaluation.to_dict())
    (out_dir / "evaluation.md").write_text(render_evaluation_markdown(evaluation), encoding="utf-8")


def render_evaluation_markdown(evaluation: PlanEvaluation) -> str:
    lines = [
        f"# Evaluation: score {evaluation.score}/100 "
        f"({'PASS' if evaluation.passed else 'FAIL'}) - "
        f"{evaluation.errors} error(s), {evaluation.warnings} warning(s)",
        "",
    ]
    for severity in Severity:
        findings = [f for f in evaluation.findings if f.severity is severity]
        if not findings:
            continue
        lines += [f"## {severity.value} ({len(findings)})", ""]
        lines += [
            f"- `{finding.rule}`{f' [{finding.where}]' if finding.where else ''}: {finding.message}"
            for finding in findings
        ]
        lines.append("")
    lines += ["## metrics", ""]
    lines += [f"- {name}: {value}" for name, value in evaluation.metrics.items()]
    return "\n".join(lines) + "\n"


def load_profile(path: Path) -> InterviewerProfile:
    return InterviewerProfile.model_validate_json(path.read_text(encoding="utf-8"))


def load_catalogue(path: Path) -> list[Exercise]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [Exercise(**row) for row in rows]


def dump_catalogue(exercises: Sequence[Exercise], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(exercise) for exercise in exercises]
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact_dir(root: Path, case: str, variant: str, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return root / f"{stamp}-{_SLUG.sub('_', case)}-{_SLUG.sub('_', variant)}"


def run_summary(run: TrainerRun) -> dict[str, Any]:
    evaluation = run.evaluation
    return {
        "case": run.case,
        "variant": run.variant.name,
        "skill": run.variant.skill,
        "prompts_root": str(run.variant.prompts_root or "packaged"),
        "skills_root": str(run.variant.skills_root or "packaged"),
        "model": run.model,
        "prompt_fingerprint": run.prompt_fingerprint,
        "status": run.status,
        "error": run.error,
        "llm_calls": len(run.calls),
        "repaired": run.repaired,
        "total_tokens": run.total_tokens,
        "latency_ms": run.latency_ms,
        "exercises_in_catalogue": len(run.exercises),
        "score": evaluation.score if evaluation else None,
        "eval_errors": evaluation.errors if evaluation else None,
        "eval_warnings": evaluation.warnings if evaluation else None,
        "token_usages": [asdict(usage) for usage in run.token_usages],
    }


def write_artifacts(run: TrainerRun, out_dir: Path) -> Path:
    """Persist everything needed to understand (and reproduce) one run.

    - ``system_prompt.txt``: the assembled prompt exactly as sent (skill + catalogue).
    - ``calls/NN_request.json`` / ``NN_response.txt``: every LLM call, repair included.
    - ``plan.json`` / ``plan.md``: the validated turn and a human-readable rendering.
    - ``evaluation.json`` / ``evaluation.md``: the skill-rule checks (``plan_evaluator``).
    - ``run.json``: summary (status, score, tokens, latency, fingerprint...).
    - ``profile.json`` / ``catalogue.json``: inputs, so the run can be replayed.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    calls_dir = out_dir / "calls"
    calls_dir.mkdir(exist_ok=True)
    for index, call in enumerate(run.calls, start=1):
        request = {"messages": call.messages, "latency_ms": call.latency_ms, "usage": call.usage}
        _write_json(calls_dir / f"{index:02d}_request.json", request)
        response = call.response if call.response is not None else f"<error> {call.error}"
        (calls_dir / f"{index:02d}_response.txt").write_text(response + "\n", encoding="utf-8")
    if run.calls and run.calls[0].messages:
        system_prompt = str(run.calls[0].messages[0]["content"])
        (out_dir / "system_prompt.txt").write_text(system_prompt, encoding="utf-8")
    if run.turn is not None:
        _write_json(out_dir / "plan.json", run.turn.model_dump(mode="json"))
        (out_dir / "plan.md").write_text(render_turn_markdown(run.turn), encoding="utf-8")
    if run.evaluation is not None:
        write_evaluation(run.evaluation, out_dir)
    _write_json(out_dir / "profile.json", run.profile.model_dump(mode="json"))
    dump_catalogue(run.exercises, out_dir / "catalogue.json")
    _write_json(out_dir / "run.json", run_summary(run))
    return out_dir


def render_turn_markdown(turn: TrainerTurn) -> str:
    lines = [f"# Trainer turn: {turn.status.value}", "", "## reply", "", turn.reply, ""]
    if turn.report:
        lines += ["## report", "", turn.report, ""]
    plan = turn.plan
    if plan is None:
        return "\n".join(lines)
    lines += [
        "## plan",
        "",
        f"goal={plan.goal} days_per_week={plan.days_per_week} environment={plan.environment}",
        "",
        f"excluded_by_injury: {plan.excluded_by_injury or '-'}",
        "",
        f"progression_notes: {plan.progression_notes}",
        "",
    ]
    for week in plan.weeks:
        weekly_sets = sum(ex.sets for day in week.days for ex in day.exercises)
        lines += [f"### Week {week.week} ({week.intensity}) - {weekly_sets} sets", ""]
        for day in week.days:
            lines.append(f"**Day {day.day} - {day.focus} (~{day.estimated_minutes} min)**")
            lines.append("")
            lines.append("| id | exercise | sets | reps | rest | rpe | notes |")
            lines.append("|---|---|---|---|---|---|---|")
            for ex in day.exercises:
                rpe = "-" if ex.rpe is None else f"{ex.rpe:g}"
                lines.append(
                    f"| {ex.exercise_id} | {ex.name} | {ex.sets} | {ex.reps} | "
                    f"{ex.rest_seconds}s | {rpe} | {ex.notes or ''} |"
                )
            lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
