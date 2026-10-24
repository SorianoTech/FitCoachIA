"""Provider-level LLM failures, shared by every agent.

The taxonomy is about the model provider, not about any one agent, so the same
codes cover the Interviewer, the Trainer and whatever comes next. The string
values are persisted in ``token_usage.status`` and queried by the Grafana
dashboards: rename the symbols freely, but never the values.
"""

from enum import StrEnum

from fitcoach.domain.token_usage import TokenUsage


class AgentErrorCode(StrEnum):
    AUTHENTICATION = "llm_authentication"
    QUOTA = "llm_quota"
    RATE_LIMITED = "llm_rate_limited"
    INVALID_REQUEST = "llm_invalid_request"
    OUTPUT_LIMIT = "llm_output_limit"
    TIMEOUT = "llm_timeout"
    UNAVAILABLE = "llm_unavailable"
    INVALID_OUTPUT = "llm_invalid_output"


class AgentError(RuntimeError):
    def __init__(
        self,
        code: AgentErrorCode,
        retryable: bool,
        token_usages: list[TokenUsage] | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.token_usages = token_usages or []
        super().__init__(code)
