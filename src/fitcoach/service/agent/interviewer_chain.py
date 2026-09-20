import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Protocol

import httpx
import openai
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from fitcoach.domain.conversation import ConversationMessage
from fitcoach.domain.interviewer_errors import InterviewerError, InterviewerErrorCode
from fitcoach.domain.interviewer_profile import InterviewerTurn
from fitcoach.domain.token_usage import TokenUsage
from fitcoach.infrastructure.config.settings import IASettings, get_ia_settings
from fitcoach.service.agent.agent_factory import build_interviewer_agent

logger = logging.getLogger(__name__)


class AsyncChatModel(Protocol):
    async def ainvoke(self, input: list[BaseMessage]) -> BaseMessage: ...


class InterviewerResultError(InterviewerError):
    def __init__(self, token_usages: list[TokenUsage] | None = None) -> None:
        super().__init__(
            InterviewerErrorCode.INVALID_OUTPUT, retryable=True, token_usages=token_usages
        )


@dataclass(frozen=True, slots=True)
class InterviewerReply:
    """``respond()``'s result: the validated turn plus one ``TokenUsage`` per LLM call.

    ``token_usages`` has two entries when the JSON-repair retry fires (the
    original malformed call still consumed tokens and must not be discarded),
    and is empty when the model/test double reports no usage metadata.
    """

    turn: InterviewerTurn
    token_usages: list[TokenUsage]


class InterviewerChain:
    def __init__(
        self,
        model: AsyncChatModel,
        model_name: str = "unknown",
        skill_name: str = "interviewer",
    ) -> None:
        self._model = model
        self._model_name = model_name
        self._agent = build_interviewer_agent(skill_name=skill_name)

    async def respond(
        self, user_message: str, history: Sequence[ConversationMessage]
    ) -> InterviewerReply:
        messages = [
            SystemMessage(content=self._agent.insert_context()),
            *self._to_langchain_messages(history),
            HumanMessage(content=user_message),
        ]
        raw_result, usage = await self._invoke(messages)
        token_usages = [usage] if usage is not None else []
        try:
            turn = InterviewerTurn.model_validate_json(raw_result)
        except ValidationError as validation_error:
            logger.debug("Interviewer result invalid; raw model output: %s", raw_result)
            logger.debug("Interviewer validation error: %s", validation_error)
            if usage is not None:
                token_usages[0] = replace(usage, status=InterviewerErrorCode.INVALID_OUTPUT.value)
            logger.debug("Interviewer result was invalid; requesting a repair")
            try:
                repaired_result, repair_usage = await self._invoke([
                    SystemMessage(
                        content=(
                            "Return only a valid JSON object matching this JSON schema. Do not return "
                            f"Markdown or prose. Schema: {InterviewerTurn.model_json_schema()}. "
                            "Correct all missing, invalid, and inconsistent fields."
                        )
                    ),
                    HumanMessage(content=raw_result),
                ])
            except InterviewerError as error:
                error.token_usages = [*token_usages, *error.token_usages]
                raise
            if repair_usage is not None:
                token_usages.append(repair_usage)
            logger.debug("Interviewer repair result: %s", repaired_result)
            try:
                turn = InterviewerTurn.model_validate_json(repaired_result)
            except ValidationError as repair_error:
                if repair_usage is not None:
                    token_usages[-1] = replace(
                        repair_usage, status=InterviewerErrorCode.INVALID_OUTPUT.value
                    )
                logger.debug("Interviewer repaired result still invalid: %s", repair_error)
                raise InterviewerResultError(token_usages) from repair_error
        return InterviewerReply(turn=turn, token_usages=token_usages)

    async def _invoke(self, messages: list[BaseMessage]) -> tuple[str, TokenUsage | None]:
        started = time.perf_counter()
        try:
            response = await self._model.ainvoke(messages)
        except Exception as exc:
            error = self._error_for_exception(exc)
            latency_ms = int((time.perf_counter() - started) * 1000)
            error.token_usages = [
                TokenUsage(
                    model=self._model_name,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    status=error.code.value,
                    latency_ms=latency_ms,
                )
            ]
            raise error from exc
        if not isinstance(response.content, str):
            latency_ms = int((time.perf_counter() - started) * 1000)
            raise InterviewerResultError([
                TokenUsage(
                    model=self._model_name,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    status=InterviewerErrorCode.INVALID_OUTPUT.value,
                    latency_ms=latency_ms,
                )
            ])
        latency_ms = int((time.perf_counter() - started) * 1000)
        return response.content.strip(), self._extract_usage(response, latency_ms)

    @staticmethod
    def _error_for_exception(error: Exception) -> InterviewerError:
        if isinstance(error, openai.LengthFinishReasonError):
            return InterviewerError(InterviewerErrorCode.OUTPUT_LIMIT, retryable=True)
        if isinstance(error, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return InterviewerError(InterviewerErrorCode.AUTHENTICATION, retryable=False)
        if isinstance(error, openai.RateLimitError):
            return InterviewerError(InterviewerErrorCode.RATE_LIMITED, retryable=True)
        if isinstance(error, openai.BadRequestError):
            return InterviewerError(InterviewerErrorCode.INVALID_REQUEST, retryable=False)
        if isinstance(error, (openai.APITimeoutError, httpx.TimeoutException, TimeoutError)):
            return InterviewerError(InterviewerErrorCode.TIMEOUT, retryable=True)
        if isinstance(error, openai.APIConnectionError):
            return InterviewerError(InterviewerErrorCode.UNAVAILABLE, retryable=True)
        if isinstance(error, openai.APIStatusError):
            return InterviewerChain._status_error(error)
        return InterviewerError(InterviewerErrorCode.UNAVAILABLE, retryable=True)

    def _extract_usage(self, response: BaseMessage, latency_ms: int) -> TokenUsage | None:
        """Normalize token counts, preferring langchain's ``usage_metadata`` over the raw payload.

        ``usage_metadata`` (langchain-core ``UsageMetadata``) uses input_tokens/
        output_tokens; the raw OpenAI ``token_usage`` dict already uses
        prompt_tokens/completion_tokens. Both are normalized to the same shape.
        """
        usage_metadata = getattr(response, "usage_metadata", None)
        if usage_metadata:
            return TokenUsage(
                model=self._model_name,
                prompt_tokens=usage_metadata.get("input_tokens", 0),
                completion_tokens=usage_metadata.get("output_tokens", 0),
                total_tokens=usage_metadata.get("total_tokens", 0),
                status="success",
                latency_ms=latency_ms,
            )
        response_metadata = getattr(response, "response_metadata", None) or {}
        token_usage = response_metadata.get("token_usage")
        if token_usage:
            return TokenUsage(
                model=self._model_name,
                prompt_tokens=token_usage.get("prompt_tokens", 0),
                completion_tokens=token_usage.get("completion_tokens", 0),
                total_tokens=token_usage.get("total_tokens", 0),
                status="success",
                latency_ms=latency_ms,
            )
        return None

    @staticmethod
    def _status_error(error: openai.APIStatusError) -> InterviewerError:
        if error.status_code in {401, 403}:
            return InterviewerError(InterviewerErrorCode.AUTHENTICATION, retryable=False)
        if error.status_code == 402:
            return InterviewerError(InterviewerErrorCode.QUOTA, retryable=False)
        if error.status_code == 429:
            return InterviewerError(InterviewerErrorCode.RATE_LIMITED, retryable=True)
        if error.status_code in {400, 422}:
            return InterviewerError(InterviewerErrorCode.INVALID_REQUEST, retryable=False)
        if error.status_code == 408:
            return InterviewerError(InterviewerErrorCode.TIMEOUT, retryable=True)
        if error.status_code >= 500:
            return InterviewerError(InterviewerErrorCode.UNAVAILABLE, retryable=True)
        return InterviewerError(InterviewerErrorCode.UNAVAILABLE, retryable=True)

    @staticmethod
    def _to_langchain_messages(history: Sequence[ConversationMessage]) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        for message in history:
            if message.role == "user":
                messages.append(HumanMessage(content=message.content))
            else:
                messages.append(AIMessage(content=message.content))
        return messages


def _build_model(settings: IASettings) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.base_url,
        api_key=settings.token,
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens or None,
        timeout=settings.timeout_seconds or None,
        model_kwargs={"response_format": {"type": "json_object"}},
    )


@lru_cache
def get_interviewer_chain() -> InterviewerChain:
    settings = get_ia_settings()
    return InterviewerChain(
        _build_model(settings), model_name=settings.model, skill_name=settings.skill
    )
