"""Chat model wrapper that records every request and raw response.

The chains only expose the validated turn; to tune a prompt you need to see what
was actually sent and what the model answered, including the rejected first
attempt and the repair. Wrapping the model keeps production code untouched.
"""

import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage

from fitcoach.service.agent.llm_chain import AsyncChatModel

logger = logging.getLogger(__name__)
_PROGRESS_INTERVAL_SECONDS = 10


async def _report_wait(call_number: int, started: float) -> None:
    while True:
        await asyncio.sleep(_PROGRESS_INTERVAL_SECONDS)
        logger.info(
            "LLM call %s: waiting for response (%.0fs elapsed)",
            call_number,
            time.perf_counter() - started,
        )


@dataclass(slots=True)
class RecordedCall:
    messages: list[dict[str, Any]]
    response: str | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: int = 0


@dataclass(slots=True)
class RecordingChatModel:
    inner: AsyncChatModel
    calls: list[RecordedCall] = field(default_factory=list)

    async def ainvoke(self, input: list[BaseMessage]) -> BaseMessage:  # noqa: A002
        call = RecordedCall(messages=[serialize_message(message) for message in input])
        self.calls.append(call)
        started = time.perf_counter()
        call_number = len(self.calls)
        logger.info(
            "LLM call %s: %s",
            call_number,
            "generating plan" if call_number == 1 else "repairing output",
        )
        progress = asyncio.create_task(_report_wait(call_number, started))
        try:
            response = await self.inner.ainvoke(input)
        except Exception as exc:
            call.error = f"{type(exc).__name__}: {exc}"
            logger.error("LLM call %s failed: %s", call_number, type(exc).__name__)
            raise
        finally:
            call.latency_ms = int((time.perf_counter() - started) * 1000)
            progress.cancel()
            with suppress(asyncio.CancelledError):
                await progress
        call.response = response.content if isinstance(response.content, str) else None
        usage = getattr(response, "usage_metadata", None)
        call.usage = dict(usage) if usage else None
        logger.info("LLM call %s: response received in %.1fs", call_number, call.latency_ms / 1000)
        return response


def serialize_message(message: BaseMessage) -> dict[str, Any]:
    return {"role": message.type, "content": message.content}
