"""CLI: generate a training plan offline and dump every artifact for inspection.

Examples (from the repository root)::

    # Only render the prompt that would be sent (no LLM call, no cost)
    uv run python -m fitcoach.devtools.trainer_debug \\
        --profile evals/trainer/profiles/beginner_gym.json \\
        --catalogue evals/trainer/catalogue.json --render-only

    # Full run against the configured LLM, with a skill being edited elsewhere
    uv run python -m fitcoach.devtools.trainer_debug \\
        --profile evals/trainer/profiles/knee_injury_home.json \\
        --catalogue evals/trainer/catalogue.json --skills-root /tmp/skills --skill trainer

    # Reproduce a real user's case: profile from the DB, catalogue from pgVector
    uv run python -m fitcoach.devtools.trainer_debug --chat-id 123 --live-retrieval \\
        --save-catalogue evals/trainer/catalogue_123.json

    # Re-score a stored run after changing the evaluator rules (no LLM call)
    uv run python -m fitcoach.devtools.trainer_debug --evaluate-run runs/trainer/<run>
"""

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from fitcoach.devtools.trainer_runner import (
    TrainerRun,
    TrainerVariant,
    artifact_dir,
    dump_catalogue,
    evaluate_run_dir,
    load_catalogue,
    load_profile,
    render_messages,
    run_summary,
    run_trainer_case,
    write_artifacts,
)
from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.infrastructure.config.settings import IASettings, get_ia_settings
from fitcoach.service.agent.plan_evaluator import PlanEvaluation, Severity
from fitcoach.service.agent.trainer_chain import build_trainer_model

DEFAULT_OUT = Path("runs/trainer")
# Rough heuristic, only to notice when the prompt grows out of proportion.
_CHARS_PER_TOKEN = 4
logger = logging.getLogger("fitcoach.devtools.trainer_debug")


def echo(text: str) -> None:
    sys.stdout.write(text + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trainer_debug", description="Run the Trainer agent offline and dump its artifacts."
    )
    parser.add_argument(
        "--case-dir",
        type=Path,
        help="Golden case folder with profile.json and catalogue.json (see evals/trainer)",
    )
    profile = parser.add_mutually_exclusive_group()
    profile.add_argument("--profile", type=Path, help="InterviewerProfile JSON file")
    profile.add_argument("--chat-id", type=int, help="Load the stored profile of this chat")
    catalogue = parser.add_mutually_exclusive_group()
    catalogue.add_argument("--catalogue", type=Path, help="Frozen exercise catalogue JSON")
    catalogue.add_argument(
        "--live-retrieval", action="store_true", help="Retrieve from embedder + pgVector"
    )
    parser.add_argument("--top-k", type=int, help="Exercises per muscle group (live retrieval)")
    parser.add_argument("--save-catalogue", type=Path, help="Write the catalogue used to a file")
    parser.add_argument("--case", help="Case name for the artifacts (default: profile stem)")
    add_variant_arguments(parser)
    add_model_arguments(parser)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Artifacts root directory")
    parser.add_argument(
        "--render-only", action="store_true", help="Write the prompt only; do not call the LLM"
    )
    parser.add_argument(
        "--evaluate-run",
        type=Path,
        metavar="RUN_DIR",
        help="Re-score a stored run (plan.json + profile.json + catalogue.json); no LLM call",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG logging")
    return parser


def add_variant_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--variant", default="default", help="Label for this prompt/skill variant")
    parser.add_argument(
        "--skill", default=None, help="Skill folder name (default: ia_trainer_skill)"
    )
    parser.add_argument(
        "--prompts-root", type=Path, help="Folder containing trainer/system_prompt.txt"
    )
    parser.add_argument("--skills-root", type=Path, help="Folder containing <skill>/SKILL.md")


def add_model_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", help="Override ia_model")
    parser.add_argument("--temperature", type=float, help="Override ia_temperature")
    parser.add_argument("--max-tokens", type=int, help="Override ia_trainer_max_tokens")
    add_timeout_argument(parser)


def positive_seconds(value: str) -> int:
    seconds = int(value)
    if seconds <= 0:
        raise argparse.ArgumentTypeError("timeout must be greater than zero")
    return seconds


def add_timeout_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--timeout",
        type=positive_seconds,
        metavar="SECONDS",
        help="Timeout per LLM request, including repair (default: ia_trainer_timeout)",
    )


def model_settings(args: argparse.Namespace) -> IASettings:
    overrides: dict[str, object] = {}
    if args.model is not None:
        overrides["model"] = args.model
    if args.temperature is not None:
        overrides["temperature"] = args.temperature
    if args.max_tokens is not None:
        overrides["trainer_max_tokens"] = args.max_tokens
    if args.timeout is not None:
        overrides["trainer_timeout"] = args.timeout
    return get_ia_settings().model_copy(update=overrides)


def variant_from_args(args: argparse.Namespace, default_skill: str = "trainer") -> TrainerVariant:
    return TrainerVariant(
        name=args.variant,
        skill=args.skill or default_skill,
        prompts_root=args.prompts_root,
        skills_root=args.skills_root,
    )


async def load_profile_from_db(chat_id: int) -> InterviewerProfile:
    from fitcoach.infrastructure.database.postgres_conversation_repository import (
        PostgresConversationRepository,
    )
    from fitcoach.infrastructure.database.session import get_engine, get_session_factory

    try:
        async with get_session_factory()() as session:
            profile = await PostgresConversationRepository(session).get_interviewer_profile(chat_id)
    finally:
        await get_engine().dispose()
    if profile is None:
        raise SystemExit(f"chat {chat_id} has no stored interviewer profile")
    return profile


async def retrieve_live(profile: InterviewerProfile, top_k: int) -> list[Exercise]:
    from fitcoach.infrastructure.ia.embedder_client import get_embedder_client
    from fitcoach.infrastructure.vectordb.pgvector_exercise_repository import (
        PgVectorExerciseRepository,
    )
    from fitcoach.infrastructure.vectordb.session import (
        close_vector_database,
        get_vector_session_factory,
    )
    from fitcoach.service.agent.exercise_retriever import ExerciseRetriever

    try:
        async with get_vector_session_factory()() as session:
            retriever = ExerciseRetriever(
                embedder=get_embedder_client(),
                exercise_repository=PgVectorExerciseRepository(session),
                top_k=top_k,
            )
            return await retriever.retrieve(profile)
    finally:
        await close_vector_database()


def print_run(run: TrainerRun, out_dir: Path) -> None:
    summary = run_summary(run)
    summary.pop("token_usages")
    echo(json.dumps(summary, ensure_ascii=False, indent=2))
    if run.evaluation is not None:
        print_findings(run.evaluation)
    echo(f"artifacts: {out_dir}")


def print_findings(evaluation: PlanEvaluation) -> None:
    echo(
        f"evaluation: score {evaluation.score}/100, "
        f"{evaluation.errors} error(s), {evaluation.warnings} warning(s)"
    )
    for finding in evaluation.findings:
        if finding.severity is Severity.INFO:
            continue
        where = f" [{finding.where}]" if finding.where else ""
        echo(f"  {finding.severity.value.upper():7} {finding.rule}{where}: {finding.message}")


DEFAULT_TOP_K = 8


async def resolve_profile(args: argparse.Namespace) -> tuple[InterviewerProfile, str]:
    if args.profile is not None:
        return load_profile(args.profile), args.case or args.profile.stem
    if args.chat_id is not None:
        return await load_profile_from_db(args.chat_id), args.case or f"chat-{args.chat_id}"
    if args.case_dir is not None:
        return load_profile(args.case_dir / "profile.json"), args.case or args.case_dir.name
    raise SystemExit("a profile is required: use --case-dir, --profile or --chat-id")


async def resolve_catalogue(
    args: argparse.Namespace, profile: InterviewerProfile, settings: IASettings | None
) -> list[Exercise]:
    if args.catalogue is not None:
        return load_catalogue(args.catalogue)
    if args.live_retrieval:
        top_k = args.top_k or (settings.rag_top_k if settings is not None else DEFAULT_TOP_K)
        return await retrieve_live(profile, top_k)
    if args.case_dir is not None:
        return load_catalogue(args.case_dir / "catalogue.json")
    raise SystemExit("a catalogue is required: use --case-dir, --catalogue or --live-retrieval")


async def main_async(args: argparse.Namespace) -> int:
    if args.evaluate_run is not None:
        evaluation = evaluate_run_dir(args.evaluate_run)
        print_findings(evaluation)
        echo(f"written: {args.evaluate_run / 'evaluation.md'}")
        return 0 if evaluation.passed else 1
    profile, case = await resolve_profile(args)
    logger.info("Profile loaded: %s", case)
    settings = None if args.render_only else model_settings(args)
    exercises = await resolve_catalogue(args, profile, settings)
    logger.info("Catalogue loaded: %s exercises", len(exercises))
    if args.save_catalogue is not None:
        dump_catalogue(exercises, args.save_catalogue)
        echo(f"catalogue saved: {args.save_catalogue} ({len(exercises)} exercises)")

    default_skill = settings.trainer_skill if settings is not None else "trainer"
    variant = variant_from_args(args, default_skill)
    out_dir = artifact_dir(args.out, case, variant.name)

    if args.render_only:
        messages = render_messages(profile, exercises, variant)
        out_dir.mkdir(parents=True, exist_ok=True)
        system_prompt = str(messages[0]["content"])
        (out_dir / "system_prompt.txt").write_text(system_prompt, encoding="utf-8")
        (out_dir / "messages.json").write_text(
            json.dumps(messages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        chars = sum(len(str(message["content"])) for message in messages)
        echo(
            f"rendered {len(messages)} messages, {chars} chars "
            f"(~{chars // _CHARS_PER_TOKEN} tokens), {len(exercises)} exercises"
        )
        echo(f"artifacts: {out_dir}")
        return 0

    if settings is None:
        raise RuntimeError("LLM settings are required unless --render-only is used")
    logger.info(
        "Starting case %s: model=%s skill=%s timeout=%ss per request retries=%s",
        case,
        settings.model,
        variant.skill,
        settings.trainer_timeout or settings.timeout_seconds,
        settings.max_retries,
    )
    run = await run_trainer_case(
        case, profile, exercises, build_trainer_model(settings), settings.model, variant
    )
    logger.info("Writing artifacts: %s", out_dir)
    write_artifacts(run, out_dir)
    print_run(run, out_dir)
    return 0 if run.status == "plan" else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)8s] %(name)s - %(message)s",
    )
    logging.getLogger("fitcoach.devtools").setLevel(logging.DEBUG if args.verbose else logging.INFO)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
