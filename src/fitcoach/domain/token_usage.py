"""Normalized token counts for a single LLM call (see docs/plan/observabilidad.md)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenUsage:
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    status: str = "success"
    latency_ms: int = 0
