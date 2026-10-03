"""The golden set must stay loadable: a broken case silently shrinks every comparison."""

from pathlib import Path

import pytest

from fitcoach.devtools.trainer_runner import load_catalogue, load_profile

CASES_ROOT = Path(__file__).resolve().parents[2] / "evals" / "trainer" / "cases"
CASES = sorted(path for path in CASES_ROOT.iterdir() if path.is_dir())


def test_the_golden_set_is_not_empty() -> None:
    assert len(CASES) >= 6


@pytest.mark.parametrize("case", CASES, ids=lambda path: path.name)
def test_case_has_a_valid_profile_and_a_non_empty_catalogue(case: Path) -> None:
    profile = load_profile(case / "profile.json")
    catalogue = load_catalogue(case / "catalogue.json")

    assert profile.commitment.days_per_week >= 1
    assert catalogue
    assert len({exercise.id for exercise in catalogue}) == len(catalogue)
