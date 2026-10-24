import csv
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from fitcoach.devtools import trainer_compare
from fitcoach.devtools.trainer_compare import (
    ComparisonVariant,
    aggregate_rows,
    comparison_rows,
    discover_cases,
    run_comparison,
)
from fitcoach.devtools.trainer_runner import dump_catalogue
from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.infrastructure.config.settings import IASettings
from tests.unit_test.conftest import build_plan_payload


def write_case(
    root: Path,
    name: str,
    profile: InterviewerProfile,
    exercises: list[Exercise],
) -> None:
    case = root / name
    case.mkdir(parents=True)
    (case / "profile.json").write_text(profile.model_dump_json(), encoding="utf-8")
    dump_catalogue(exercises, case / "catalogue.json")


def model() -> MagicMock:
    payload = {
        "status": "plan",
        "reply": "Listo",
        "report": "Plan listo",
        "plan": build_plan_payload(),
    }
    chat = MagicMock()
    chat.ainvoke = AsyncMock(
        return_value=AIMessage(
            content=json.dumps(payload),
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
    )
    return chat


def test_discover_cases_requires_complete_case_directories(tmp_path: Path) -> None:
    (tmp_path / "incomplete").mkdir()

    with pytest.raises(SystemExit, match="no trainer cases"):
        discover_cases(tmp_path)


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "1.5"])
def test_compare_rejects_invalid_timeouts(timeout: str) -> None:
    with pytest.raises(SystemExit) as error:
        trainer_compare.build_parser().parse_args(["--timeout", timeout])
    assert error.value.code == 2


def test_compare_applies_timeout_override(
    tmp_path: Path,
    profile: InterviewerProfile,
    exercises: list[Exercise],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = tmp_path / "cases"
    write_case(cases, "case-a", profile, exercises)
    settings = IASettings(
        _env_file=None,  # type: ignore[call-arg]
        base_url="http://llm",
        token="test",  # noqa: S106
        model="model-a",
        temperature=1,
    )
    monkeypatch.setattr(trainer_compare, "get_ia_settings", lambda: settings)
    build = MagicMock(return_value=model())
    monkeypatch.setattr(trainer_compare, "build_trainer_model", build)

    code = trainer_compare.main([
        "--cases-root",
        str(cases),
        "--out",
        str(tmp_path / "runs"),
        "--timeout",
        "300",
    ])

    assert code == 0
    assert build.call_args.args[0].trainer_timeout == 300
    assert settings.trainer_timeout == 60


@pytest.mark.asyncio
async def test_runs_every_case_variant_and_writes_comparison(
    tmp_path: Path,
    profile: InterviewerProfile,
    exercises: list[Exercise],
) -> None:
    cases = tmp_path / "cases"
    write_case(cases, "case-b", profile, exercises)
    write_case(cases, "case-a", profile, exercises)
    variants = [
        ComparisonVariant("trainer", "model-a"),
        ComparisonVariant("trainer-dev", "model-b"),
    ]
    built: list[str] = []

    def factory(model_name: str) -> MagicMock:
        built.append(model_name)
        return model()

    out = tmp_path / "comparison"
    runs = await run_comparison(cases, variants, factory, out)

    assert len(runs) == 4
    assert built == ["model-a", "model-b"]
    assert [row["case"] for row in comparison_rows(runs)] == [
        "case-a",
        "case-a",
        "case-b",
        "case-b",
    ]
    aggregates = aggregate_rows(runs)
    assert [row["variant"] for row in aggregates] == [
        "trainer-dev@model-b",
        "trainer@model-a",
    ]
    assert all(row["total_tokens"] == 30 for row in aggregates)
    assert (out / "comparison.md").is_file()
    payload = json.loads((out / "comparison.json").read_text(encoding="utf-8"))
    assert len(payload["results"]) == 4
    with (out / "comparison.csv").open(encoding="utf-8") as file:
        assert len(list(csv.DictReader(file))) == 4
    assert (out / "runs" / "case-a" / "trainer@model-a" / "run.json").is_file()
