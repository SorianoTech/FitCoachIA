"""Chat model wrapper that records every request and raw response.

The chains only expose the validated turn; to tune a prompt you need to see what
was actually sent and what the model answered, including the rejected first
attempt and the repair. Wrapping the model keeps production code untouched.
"""

import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage

from fitcoach.service.agent.llm_chain import AsyncChatModel


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
        try:
            response = await self.inner.ainvoke(input)
        except Exception as exc:
            call.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            call.latency_ms = int((time.perf_counter() - started) * 1000)
        call.response = response.content if isinstance(response.content, str) else None
        usage = getattr(response, "usage_metadata", None)
        call.usage = dict(usage) if usage else None
        return response


def serialize_message(message: BaseMessage) -> dict[str, Any]:
    return {"role": message.type, "content": message.content}
