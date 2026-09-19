from enum import StrEnum

from fitcoach.domain.token_usage import TokenUsage


class InterviewerErrorCode(StrEnum):
    AUTHENTICATION = "llm_authentication"
    QUOTA = "llm_quota"
    RATE_LIMITED = "llm_rate_limited"
    INVALID_REQUEST = "llm_invalid_request"
    OUTPUT_LIMIT = "llm_output_limit"
    TIMEOUT = "llm_timeout"
    UNAVAILABLE = "llm_unavailable"
    INVALID_OUTPUT = "llm_invalid_output"


class InterviewerError(RuntimeError):
    def __init__(
        self,
        code: InterviewerErrorCode,
        retryable: bool,
        token_usages: list[TokenUsage] | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.token_usages = token_usages or []
        super().__init__(code)
