from enum import StrEnum


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
    def __init__(self, code: InterviewerErrorCode, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)
