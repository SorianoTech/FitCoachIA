from datetime import UTC, datetime, timedelta

import pytest

from fitcoach.domain.training_evaluation import (
    due_at,
    due_week,
    is_superseded,
    score_from_option,
    upcoming_polls,
)

_START = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


class TestDueWeek:
    def test_no_poll_is_due_before_the_first_week_ends(self) -> None:
        assert due_week(_START, _START + timedelta(days=6, hours=23)) is None

    def test_first_week_is_due_after_seven_days(self) -> None:
        assert due_week(_START, _START + timedelta(days=7)) == 1

    def test_returns_only_the_most_recent_due_week(self) -> None:
        assert due_week(_START, _START + timedelta(days=22)) == 3

    def test_never_goes_beyond_the_last_week_of_the_mesocycle(self) -> None:
        assert due_week(_START, _START + timedelta(days=60)) == 4

    def test_rejects_naive_dates(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            due_week(_START.replace(tzinfo=None), _START + timedelta(days=7))


class TestIsSuperseded:
    @pytest.mark.parametrize(("days", "week"), [(8, 1), (22, 3), (60, 4)])
    def test_the_latest_due_week_is_not_superseded(self, days: int, week: int) -> None:
        assert not is_superseded(_START, week, _START + timedelta(days=days))

    def test_an_older_week_is_superseded_by_a_newer_due_one(self) -> None:
        assert is_superseded(_START, 1, _START + timedelta(days=15))

    def test_an_undated_cycle_supersedes_everything(self) -> None:
        assert is_superseded(None, 1, _START)


class TestDueAt:
    def test_each_week_is_due_seven_days_after_the_previous(self) -> None:
        assert due_at(_START, 1) == _START + timedelta(days=7)
        assert due_at(_START, 4) == _START + timedelta(days=28)


class TestUpcomingPolls:
    def test_a_cycle_starting_now_schedules_its_four_weeks(self) -> None:
        assert upcoming_polls(_START, _START) == [
            (week, _START + timedelta(days=7 * week)) for week in (1, 2, 3, 4)
        ]

    def test_a_cycle_starting_in_the_future_schedules_its_four_weeks(self) -> None:
        assert [week for week, _ in upcoming_polls(_START, _START - timedelta(days=3))] == [
            1,
            2,
            3,
            4,
        ]

    def test_weeks_already_past_are_skipped(self) -> None:
        assert [week for week, _ in upcoming_polls(_START, _START + timedelta(days=10))] == [
            2,
            3,
            4,
        ]

    def test_a_week_due_exactly_now_is_skipped(self) -> None:
        assert [week for week, _ in upcoming_polls(_START, _START + timedelta(days=7))] == [
            2,
            3,
            4,
        ]

    def test_nothing_is_scheduled_once_the_mesocycle_is_over(self) -> None:
        assert upcoming_polls(_START, _START + timedelta(days=28)) == []

    def test_rejects_naive_dates(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            upcoming_polls(_START.replace(tzinfo=None), _START)


class TestScoreFromOption:
    @pytest.mark.parametrize("option", [0, 3, 5])
    def test_the_option_index_is_the_score(self, option: int) -> None:
        assert score_from_option([option]) == option

    def test_a_retracted_vote_has_no_score(self) -> None:
        assert score_from_option([]) is None

    @pytest.mark.parametrize("option", [-1, 6])
    def test_rejects_an_option_outside_the_scale(self, option: int) -> None:
        with pytest.raises(ValueError, match="outside"):
            score_from_option([option])
