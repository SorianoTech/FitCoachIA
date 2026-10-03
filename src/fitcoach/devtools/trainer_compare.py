"""Run the frozen trainer cases across skill/model variants and compare them."""

import argparse
import asyncio
import csv
import json
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fitcoach.devtools.trainer_debug import add_timeout_argument
from fitcoach.devtools.trainer_runner import (
    TrainerRun,
    TrainerVariant,
    load_catalogue,
    load_profile,
    run_summary,
    run_trainer_case,
    write_artifacts,
)
from fitcoach.infrastructure.config.settings import get_ia_settings
from fitcoach.service.agent.llm_chain import AsyncChatModel
from fitcoach.service.agent.trainer_chain import build_trainer_model

DEFAULT_CASES = Path("evals/trainer/cases")
DEFAULT_OUT = Path("runs/trainer-comparisons")
logger = logging.getLogger("fitcoach.devtools.trainer_compare")
SUMMARY_FIELDS = (
    "case",
    "variant",
    "skill",
    "model",
    "status",
    "score",
    "eval_errors",
    "eval_warnings",
    "total_tokens",
    "latency_ms",
    "llm_calls",
    "repaired",
    "prompt_fingerprint",
)


@dataclass(frozen=True, slots=True)
class ComparisonVariant:
    skill: str
    model: str
    prompts_root: Path | None = None
    skills_root: Path | None = None

    @property
    def name(self) -> str:
        return f"{self.skill}@{self.model}"

    def trainer_variant(self) -> TrainerVariant:
        return TrainerVariant(self.name, self.skill, self.prompts_root, self.skills_root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trainer_compare",
        description="Compare Trainer skills/models over the frozen golden cases.",
    )
    parser.add_argument("--cases-root", type=Path, default=DEFAULT_CASES)
    parser.add_argument(
        "--skill",
        action="append",
        dest="skills",
        help="Skill folder to evaluate; repeat for several (default: configured skill)",
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="Model to evaluate; repeat for several (default: configured model)",
    )
    parser.add_argument("--prompts-root", type=Path)
    parser.add_argument("--skills-root", type=Path)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--max-tokens", type=int)
    add_timeout_argument(parser)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def comparison_dir(root: Path, now: datetime | None = None) -> Path:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    return root / stamp


def discover_cases(root: Path) -> list[Path]:
    cases = sorted(
        path
        for path in root.iterdir()
        if path.is_dir()
        and (path / "profile.json").is_file()
        and (path / "catalogue.json").is_file()
    )
    if not cases:
        raise SystemExit(f"no trainer cases found in {root}")
    return cases


async def run_comparison(
    cases_root: Path,
    variants: Sequence[ComparisonVariant],
    model_factory: Callable[[str], AsyncChatModel],
    out_dir: Path,
) -> list[TrainerRun]:
    runs: list[TrainerRun] = []
    for variant in variants:
        model = model_factory(variant.model)
        trainer_variant = variant.trainer_variant()
        for case_dir in discover_cases(cases_root):
            profile = load_profile(case_dir / "profile.json")
            catalogue = load_catalogue(case_dir / "catalogue.json")
            run = await run_trainer_case(
                case_dir.name,
                profile,
                catalogue,
                model,
                variant.model,
                trainer_variant,
            )
            run_dir = out_dir / "runs" / case_dir.name / variant.name
            write_artifacts(run, run_dir)
            runs.append(run)
    write_comparison(runs, out_dir)
    return runs


def comparison_rows(runs: Sequence[TrainerRun]) -> list[dict[str, Any]]:
    return [
        {field: run_summary(run)[field] for field in SUMMARY_FIELDS}
        for run in sorted(runs, key=lambda item: (item.case, item.variant.name))
    ]


def aggregate_rows(runs: Sequence[TrainerRun]) -> list[dict[str, Any]]:
    variants = sorted({run.variant.name for run in runs})
    rows: list[dict[str, Any]] = []
    for variant in variants:
        selected = [run for run in runs if run.variant.name == variant]
        scores = [run.evaluation.score for run in selected if run.evaluation is not None]
        rows.append({
            "variant": variant,
            "cases": len(selected),
            "plans": sum(run.status == "plan" for run in selected),
            "average_score": round(sum(scores) / len(scores), 1) if scores else None,
            "evaluation_errors": sum(
                run.evaluation.errors for run in selected if run.evaluation is not None
            ),
            "evaluation_warnings": sum(
                run.evaluation.warnings for run in selected if run.evaluation is not None
            ),
            "repairs": sum(run.repaired for run in selected),
            "total_tokens": sum(run.total_tokens for run in selected),
            "total_latency_ms": sum(run.latency_ms for run in selected),
        })
    return rows


def write_comparison(runs: Sequence[TrainerRun], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = comparison_rows(runs)
    aggregates = aggregate_rows(runs)
    payload = {"results": rows, "aggregates": aggregates}
    (out_dir / "comparison.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (out_dir / "comparison.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (out_dir / "comparison.md").write_text(
        render_comparison_markdown(rows, aggregates), encoding="utf-8"
    )


def render_comparison_markdown(
    rows: Sequence[dict[str, Any]], aggregates: Sequence[dict[str, Any]]
) -> str:
    lines = [
        "# Trainer comparison",
        "",
        "## Variants",
        "",
        "| variant | plans | avg score | errors | warnings | repairs | tokens | latency ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in aggregates:
        lines.append(
            f"| {row['variant']} | {row['plans']}/{row['cases']} | "
            f"{_display(row['average_score'])} | {row['evaluation_errors']} | "
            f"{row['evaluation_warnings']} | {row['repairs']} | {row['total_tokens']} | "
            f"{row['total_latency_ms']} |"
        )
    lines += [
        "",
        "## Cases",
        "",
        "| case | variant | status | score | errors | warnings | repairs | tokens | latency ms |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case']} | {row['variant']} | {row['status']} | "
            f"{_display(row['score'])} | {_display(row['eval_errors'])} | "
            f"{_display(row['eval_warnings'])} | {int(bool(row['repaired']))} | "
            f"{row['total_tokens']} | {row['latency_ms']} |"
        )
    return "\n".join(lines) + "\n"


def _display(value: object) -> str:
    return "-" if value is None else str(value)


async def main_async(args: argparse.Namespace) -> int:
    settings = get_ia_settings()
    skills = args.skills or [settings.trainer_skill]
    models = args.models or [settings.model]
    variants = [
        ComparisonVariant(skill, model, args.prompts_root, args.skills_root)
        for skill in skills
        for model in models
    ]
    overrides: dict[str, object] = {}
    if args.temperature is not None:
        overrides["temperature"] = args.temperature
    if args.max_tokens is not None:
        overrides["trainer_max_tokens"] = args.max_tokens
    if args.timeout is not None:
        overrides["trainer_timeout"] = args.timeout

    def model_factory(model: str) -> AsyncChatModel:
        configured = settings.model_copy(update={**overrides, "model": model})
        logger.info(
            "Starting model %s: timeout=%ss per request retries=%s",
            model,
            configured.trainer_timeout or configured.timeout_seconds,
            configured.max_retries,
        )
        return build_trainer_model(configured)

    out_dir = comparison_dir(args.out)
    runs = await run_comparison(args.cases_root, variants, model_factory, out_dir)
    aggregates = aggregate_rows(runs)
    sys.stdout.write(render_comparison_markdown(comparison_rows(runs), aggregates))
    sys.stdout.write(f"\nartifacts: {out_dir}\n")
    return 1 if any(run.status == "error" for run in runs) else 0


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
