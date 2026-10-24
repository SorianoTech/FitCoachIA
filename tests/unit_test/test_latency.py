import asyncio
import logging

import pytest

from fitcoach.infrastructure.observability.latency import latency_phase, timed


@pytest.mark.asyncio
async def test_latency_preserves_results_and_separates_concurrent_actions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    @timed("workflow", action="renewal")
    async def renewal() -> int:
        await asyncio.sleep(0)
        with latency_phase("llm", model="test-model"):
            return 42

    @timed("workflow", action="exercise_swap")
    async def swap() -> int:
        await asyncio.sleep(0)
        with latency_phase("retrieval"):
            return 7

    with caplog.at_level(logging.INFO):
        assert await asyncio.gather(renewal(), swap()) == [42, 7]
        with latency_phase("validation"):
            pass
    assert "action=renewal phase=llm result=ok" in caplog.text
    assert "action=exercise_swap phase=retrieval result=ok" in caplog.text
    assert "action=other phase=validation" in caplog.text
    assert "duration_ms=" in caplog.text


@pytest.mark.asyncio
async def test_latency_errors_do_not_export_sensitive_arguments(
    caplog: pytest.LogCaptureFixture,
) -> None:
    @timed("workflow", action="exercise_swap")
    async def fail(private_text: str) -> None:
        raise ValueError(private_text)

    with caplog.at_level(logging.INFO), pytest.raises(ValueError, match="private"):
        await fail("private user data")
    assert "result=error" in caplog.text
    assert "private user data" not in caplog.text
