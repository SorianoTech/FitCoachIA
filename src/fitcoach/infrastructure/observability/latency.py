"""Low-cardinality timings; never export arguments or exception messages."""

import logging
import time
from collections.abc import Awaitable, Callable, Coroutine, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from fitcoach.infrastructure.observability.telemetry import get_tracer

logger = logging.getLogger(__name__)
_tracer = get_tracer(__name__)
_action: ContextVar[str] = ContextVar("latency_action", default="other")
P = ParamSpec("P")
T = TypeVar("T")


@contextmanager
def latency_phase(phase: str, *, model: str | None = None) -> Iterator[None]:
    started = time.perf_counter()
    result = "ok"
    with _tracer.start_as_current_span(
        f"training.{phase}", record_exception=False, set_status_on_exception=False
    ) as span:
        span.set_attribute("training.action", _action.get())
        span.set_attribute("training.phase", phase)
        if model:
            span.set_attribute("llm.model", model)
        try:
            yield
        except BaseException:
            result = "error"
            raise
        finally:
            duration = (time.perf_counter() - started) * 1000
            span.set_attribute("training.result", result)
            span.set_attribute("training.duration_ms", duration)
            logger.info(
                "training_latency action=%s phase=%s result=%s duration_ms=%.3f",
                _action.get(),
                phase,
                result,
                duration,
            )


def timed(
    phase: str, *, action: str | None = None
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Coroutine[Any, Any, T]]]:
    def decorate(function: Callable[P, Awaitable[T]]) -> Callable[P, Coroutine[Any, Any, T]]:
        @wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            token = _action.set(action) if action else None
            try:
                with latency_phase(phase):
                    return await function(*args, **kwargs)
            finally:
                if token is not None:
                    _action.reset(token)

        return wrapped

    return decorate
