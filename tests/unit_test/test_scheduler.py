import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError
from telegram import Bot
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError

from fitcoach.domain.constants import Constants
from fitcoach.domain.scheduled_job import ClaimedJob, JobOutcome, JobState, JobType
from fitcoach.domain.training_evaluation import MAX_SCORE
from fitcoach.infrastructure.config.settings import (
    EvaluationSettings,
    SchedulerSettings,
    TrainingSettings,
)
from fitcoach.infrastructure.jobs import scheduler
from fitcoach.infrastructure.jobs.scheduler import JobScheduler, poll_question
from fitcoach.repository.evaluation_repository import PollTarget
from fitcoach.repository.job_repository import JobConflictError
from fitcoach.repository.training_repository import ReminderTarget

_NOW = datetime(2026, 1, 8, 9, 0, tzinfo=UTC)
_STARTED = _NOW - timedelta(days=8)
_JOB_ID = UUID("6f1c2d3e-0000-4000-8000-000000000001")


def _job(
    job_type: JobType = JobType.EVALUATION_POLL, attempts: int = 1, week: int = 1
) -> ClaimedJob:
    payload: dict[str, object] = {"mesocycle_id": 3}
    if job_type == JobType.EVALUATION_POLL:
        payload["week_number"] = week
    return ClaimedJob(
        id=_JOB_ID,
        job_type=job_type,
        chat_id=7,
        payload=payload,
        attempts=attempts,
        execution_date=_NOW - timedelta(hours=1),
    )


def _target(started_at: datetime | None = _STARTED) -> PollTarget:
    return PollTarget(
        mesocycle_id=3, started_at=started_at, thread_id=22, plan_id=9, goal="gain_muscle"
    )


class _Fixture:
    def __init__(self) -> None:
        self.session = AsyncMock()
        self.session_opened = 0
        self.jobs = AsyncMock()
        self.jobs.claim.return_value = None
        self.evaluations = AsyncMock()
        self.evaluations.open_current_plan.return_value = _target()
        self.evaluations.previous_unanswered.return_value = []
        self.training = AsyncMock()
        self.training.reminder_target.return_value = ReminderTarget(thread_id=22)
        self.bot = AsyncMock(spec=Bot)
        self.bot.send_poll.return_value = MagicMock(message_id=555, poll=MagicMock(id="poll-1"))

    def factory(self) -> MagicMock:
        context = MagicMock()
        context.__aenter__ = AsyncMock(side_effect=self._open)
        context.__aexit__ = AsyncMock(return_value=None)
        return MagicMock(return_value=context)

    async def _open(self) -> AsyncMock:
        self.session_opened += 1
        return self.session

    def queue(self, *jobs: ClaimedJob) -> None:
        pending = list(jobs)

        def claim(
            _now: datetime, _lock: timedelta, types: tuple[JobType, ...]
        ) -> ClaimedJob | None:
            for job in pending:
                if job.job_type in types:
                    pending.remove(job)
                    return job
            return None

        self.jobs.claim.side_effect = claim

    def outcomes(self) -> list[JobOutcome]:
        return [call.args[1] for call in self.jobs.finish.await_args_list]


@pytest.fixture
def fixture(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Fixture]:
    fake = _Fixture()
    monkeypatch.setattr(scheduler, "PostgresJobRepository", lambda _session: fake.jobs)
    monkeypatch.setattr(
        scheduler, "PostgresEvaluationRepository", lambda _session: fake.evaluations
    )
    monkeypatch.setattr(scheduler, "PostgresTrainingRepository", lambda _session: fake.training)
    return fake


def _scheduler(fake: _Fixture, **evaluation: object) -> JobScheduler:
    return JobScheduler(
        fake.factory(),
        fake.bot,
        SchedulerSettings(_env_file=None, enabled=True),
        TrainingSettings(_env_file=None),
        EvaluationSettings(_env_file=None, **evaluation),
        clock=lambda: _NOW,
    )


class TestPollTexts:
    def test_the_question_names_the_week_and_the_goal(self) -> None:
        assert (
            poll_question(2, "gain_muscle")
            == "Semana 2 de tu plan para ganar músculo: ¿qué te está pareciendo?"
        )

    @pytest.mark.parametrize("goal", [None, "unknown_goal"])
    def test_without_a_known_goal_the_question_stays_generic(self, goal: str | None) -> None:
        assert poll_question(3, goal) == "Semana 3 de tu plan: ¿qué te está pareciendo?"

    def test_there_is_one_option_per_score(self) -> None:
        options = Constants.EVALUATION_POLL_OPTIONS

        assert len(options) == MAX_SCORE + 1
        assert [option.split(" - ")[0] for option in options] == [
            str(score) for score in range(MAX_SCORE + 1)
        ]


# --- dispatch -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_job_type_is_claimed_in_one_session(fixture: _Fixture) -> None:
    await _scheduler(fixture).tick()

    assert [call.args[2] for call in fixture.jobs.claim.await_args_list] == [
        (JobType.TRAINING_REMINDER,),
        (JobType.EVALUATION_POLL,),
    ]
    assert fixture.session_opened == 1


@pytest.mark.asyncio
async def test_claim_uses_the_lock_timeout_of_each_type(fixture: _Fixture) -> None:
    await _scheduler(fixture, sending_timeout_seconds=60).tick()

    locks = {call.args[2]: call.args[1] for call in fixture.jobs.claim.await_args_list}
    assert locks[(JobType.EVALUATION_POLL,)] == timedelta(seconds=60)
    assert locks[(JobType.TRAINING_REMINDER,)] == timedelta(seconds=120)


@pytest.mark.asyncio
async def test_each_type_stops_at_its_own_batch_size(fixture: _Fixture) -> None:
    fixture.jobs.claim.side_effect = lambda _now, _lock, types: (
        _job(types[0]) if types[0] == JobType.EVALUATION_POLL else None
    )

    processed = await _scheduler(fixture, batch_size=2).tick()

    assert processed == 2
    assert fixture.jobs.claim.await_count == 3


# --- training reminder --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_due_reminder_is_sent_to_the_cycle_thread(fixture: _Fixture) -> None:
    fixture.queue(_job(JobType.TRAINING_REMINDER))

    await _scheduler(fixture).tick()

    kwargs = fixture.bot.send_message.await_args.kwargs
    assert (kwargs["chat_id"], kwargs["message_thread_id"]) == (7, 22)
    assert kwargs["text"] == Constants.TRAINING_DUE_MESSAGE
    assert [outcome.state for outcome in fixture.outcomes()] == [JobState.DONE]


@pytest.mark.asyncio
async def test_a_reminder_that_no_longer_applies_is_cancelled_without_sending(
    fixture: _Fixture,
) -> None:
    fixture.training.reminder_target.return_value = None
    fixture.queue(_job(JobType.TRAINING_REMINDER))

    await _scheduler(fixture).tick()

    fixture.bot.send_message.assert_not_awaited()
    assert [outcome.state for outcome in fixture.outcomes()] == [JobState.CANCELLED]


# --- evaluation poll ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_due_poll_is_sent_non_anonymous_and_recorded(fixture: _Fixture) -> None:
    fixture.queue(_job(week=1))

    await _scheduler(fixture).tick()

    kwargs = fixture.bot.send_poll.await_args.kwargs
    assert (kwargs["chat_id"], kwargs["message_thread_id"]) == (7, 22)
    assert kwargs["question"] == poll_question(1, "gain_muscle")
    assert list(kwargs["options"]) == list(Constants.EVALUATION_POLL_OPTIONS)
    assert kwargs["is_anonymous"] is False
    assert kwargs["allows_multiple_answers"] is False
    assert kwargs["allows_revoting"] is False
    saved = fixture.evaluations.save_sent.await_args.args[0]
    assert (saved.poll_id, saved.message_id, saved.week_number, saved.sent_at) == (
        "poll-1",
        555,
        1,
        _NOW,
    )
    assert [outcome.state for outcome in fixture.outcomes()] == [JobState.DONE]


@pytest.mark.asyncio
async def test_previous_unanswered_polls_are_closed_before_sending(fixture: _Fixture) -> None:
    fixture.evaluations.previous_unanswered.return_value = [1001, 1002]
    fixture.queue(_job())

    await _scheduler(fixture).tick()

    calls = [name for name, *_ in fixture.bot.mock_calls if name in ("stop_poll", "send_poll")]
    assert calls == ["stop_poll", "stop_poll", "send_poll"]


@pytest.mark.asyncio
async def test_failing_to_close_a_previous_poll_does_not_block_the_new_one(
    fixture: _Fixture,
) -> None:
    fixture.evaluations.previous_unanswered.return_value = [1001]
    fixture.bot.stop_poll.side_effect = BadRequest("Poll has already been closed")
    fixture.queue(_job())

    await _scheduler(fixture).tick()

    fixture.bot.send_poll.assert_awaited_once()
    assert [outcome.state for outcome in fixture.outcomes()] == [JobState.DONE]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "week"),
    [(None, 1), (_target(started_at=None), 1), (_target(), 0)],
    ids=["cycle-closed", "undated-cycle", "superseded-week"],
)
async def test_a_poll_that_no_longer_applies_is_cancelled_without_sending(
    fixture: _Fixture, target: PollTarget | None, week: int
) -> None:
    fixture.evaluations.open_current_plan.return_value = target
    fixture.queue(_job(week=week))

    await _scheduler(fixture).tick()

    fixture.bot.send_poll.assert_not_awaited()
    fixture.evaluations.save_sent.assert_not_awaited()
    assert [outcome.state for outcome in fixture.outcomes()] == [JobState.CANCELLED]


# --- logs ---------------------------------------------------------------------


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records]


@pytest.mark.asyncio
@pytest.mark.parametrize("job_type", list(JobType))
async def test_a_sent_job_logs_its_type_when_claimed_and_finished(
    fixture: _Fixture, caplog: pytest.LogCaptureFixture, job_type: JobType
) -> None:
    fixture.queue(_job(job_type))
    caplog.set_level("INFO", logger=scheduler.__name__)

    await _scheduler(fixture).tick()

    messages = _messages(caplog)
    assert f"Job {_JOB_ID} ({job_type}) claimed: chat=7 attempt=1" in messages[0]
    assert f"Job {_JOB_ID} ({job_type}) finished: state=done retry_at=None" in messages


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job", "reason"),
    [
        (_job(JobType.TRAINING_REMINDER), "reminder no longer due"),
        (_job(week=1), "no open cycle with a current plan"),
        (_job(week=0), "week 0 is no longer the current one"),
    ],
    ids=["reminder-not-due", "poll-cycle-closed", "poll-superseded"],
)
async def test_a_cancelled_job_logs_why(
    fixture: _Fixture, caplog: pytest.LogCaptureFixture, job: ClaimedJob, reason: str
) -> None:
    fixture.training.reminder_target.return_value = None
    if reason.startswith("no open cycle"):
        fixture.evaluations.open_current_plan.return_value = None
    fixture.queue(job)
    caplog.set_level("INFO", logger=scheduler.__name__)

    await _scheduler(fixture).tick()

    messages = _messages(caplog)
    assert f"Job {_JOB_ID} ({job.job_type}) cancelled: {reason}" in messages
    assert f"Job {_JOB_ID} ({job.job_type}) finished: state=cancelled retry_at=None" in messages


@pytest.mark.asyncio
async def test_a_telegram_answer_without_a_poll_fails_the_job(fixture: _Fixture) -> None:
    fixture.bot.send_poll.return_value = MagicMock(message_id=1, poll=None)
    fixture.queue(_job())

    await _scheduler(fixture).tick()

    fixture.evaluations.save_sent.assert_not_awaited()
    assert [outcome.state for outcome in fixture.outcomes()] == [JobState.FAILED]


# --- failures -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_reschedules_the_job_for_what_telegram_asks(fixture: _Fixture) -> None:
    fixture.bot.send_poll.side_effect = RetryAfter(30)
    fixture.queue(_job())

    await _scheduler(fixture).tick()

    assert fixture.outcomes() == [JobOutcome.retry(_NOW + timedelta(seconds=30))]
    fixture.evaluations.save_sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_network_error_is_retried_with_the_configured_delay(fixture: _Fixture) -> None:
    fixture.bot.send_message.side_effect = NetworkError("offline")
    fixture.queue(_job(JobType.TRAINING_REMINDER))

    await _scheduler(fixture).tick()

    assert fixture.outcomes() == [JobOutcome.retry(_NOW + timedelta(seconds=60))]


@pytest.mark.asyncio
async def test_network_error_on_the_last_attempt_fails_the_job(fixture: _Fixture) -> None:
    fixture.bot.send_message.side_effect = NetworkError("offline")
    fixture.queue(_job(JobType.TRAINING_REMINDER, attempts=5))

    await _scheduler(fixture).tick()

    assert fixture.outcomes() == [JobOutcome.failed()]


@pytest.mark.asyncio
async def test_a_blocked_bot_fails_the_job(fixture: _Fixture) -> None:
    fixture.bot.send_poll.side_effect = Forbidden("bot was blocked by the user")
    fixture.queue(_job())

    await _scheduler(fixture).tick()

    assert fixture.outcomes() == [JobOutcome.failed()]


@pytest.mark.asyncio
async def test_an_unexpected_telegram_error_fails_the_job_and_the_batch_goes_on(
    fixture: _Fixture, caplog: pytest.LogCaptureFixture
) -> None:
    fixture.bot.send_message.side_effect = [TelegramError("boom"), None]
    fixture.queue(_job(JobType.TRAINING_REMINDER), _job(JobType.TRAINING_REMINDER))

    assert await _scheduler(fixture).tick() == 2

    assert fixture.outcomes() == [JobOutcome.failed(), JobOutcome.done()]
    assert any("unexpected=True" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_a_job_that_exhausted_its_attempts_is_failed_without_running(
    fixture: _Fixture,
) -> None:
    fixture.queue(_job(attempts=4))

    await _scheduler(fixture, max_attempts=3).tick()

    fixture.bot.send_poll.assert_not_awaited()
    assert fixture.outcomes() == [JobOutcome.failed()]


@pytest.mark.asyncio
async def test_a_crashing_handler_fails_its_job_and_rolls_back(fixture: _Fixture) -> None:
    fixture.evaluations.open_current_plan.side_effect = RuntimeError("bug")
    fixture.queue(_job())

    await _scheduler(fixture).tick()

    fixture.session.rollback.assert_awaited_once()
    assert fixture.outcomes() == [JobOutcome.failed()]


@pytest.mark.asyncio
async def test_a_database_error_inside_a_handler_aborts_the_tick(fixture: _Fixture) -> None:
    fixture.evaluations.open_current_plan.side_effect = OperationalError("select", {}, Exception())
    fixture.queue(_job())

    with pytest.raises(OperationalError):
        await _scheduler(fixture).tick()

    fixture.jobs.finish.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_lost_lease_is_logged_and_the_batch_goes_on(
    fixture: _Fixture, caplog: pytest.LogCaptureFixture
) -> None:
    fixture.jobs.finish.side_effect = [JobConflictError("lock expired"), None]
    fixture.queue(_job(JobType.TRAINING_REMINDER), _job(JobType.TRAINING_REMINDER))

    assert await _scheduler(fixture).tick() == 2

    assert any("lease expired" in record.getMessage() for record in caplog.records)


# --- run loop -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_keeps_going_after_a_failed_tick_and_stops_on_the_event(
    fixture: _Fixture,
) -> None:
    job_scheduler = _scheduler(fixture)
    stop = asyncio.Event()
    ticks = 0

    async def flaky_tick() -> int:
        nonlocal ticks
        ticks += 1
        if ticks == 1:
            raise OperationalError("select", {}, Exception())
        stop.set()
        return 0

    job_scheduler.tick = flaky_tick  # type: ignore[method-assign]
    job_scheduler._interval = 0  # noqa: SLF001

    await asyncio.wait_for(job_scheduler.run(stop), timeout=5)

    assert ticks == 2


@pytest.mark.asyncio
async def test_run_does_not_tick_when_already_stopped(fixture: _Fixture) -> None:
    stop = asyncio.Event()
    stop.set()

    await _scheduler(fixture).run(stop)

    assert fixture.session_opened == 0
