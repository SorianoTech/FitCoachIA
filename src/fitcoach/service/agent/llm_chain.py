"""Shared LLM plumbing: one invocation, token accounting and JSON validation.

Every agent talks to the same OpenAI-compatible endpoint and owes the same
three things: a normalized ``TokenUsage`` per call (including the calls that
failed), provider exceptions mapped to a safe ``AgentError``, and a strict
Pydantic contract with a single repair attempt when the model returns something
that does not validate.

Agent-specific behaviour -- which prompt is composed, what the model is asked
for, what counts as a valid turn -- stays in the subclasses.
"""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Protocol, TypeVar

import httpx
import openai
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from fitcoach.domain.agent_errors import AgentError, AgentErrorCode
from fitcoach.domain.conversation import ConversationMessage
from fitcoach.domain.token_usage import TokenUsage

logger = logging.getLogger(__name__)

TurnT = TypeVar("TurnT", bound=BaseModel)


class AsyncChatModel(Protocol):
    async def ainvoke(self, input: list[BaseMessage]) -> BaseMessage: ...


class InvalidModelOutputError(AgentError):
    """The model returned non-text content, or JSON that never validated."""

    def __init__(self, token_usages: list[TokenUsage] | None = None) -> None:
        super().__init__(AgentErrorCode.INVALID_OUTPUT, retryable=True, token_usages=token_usages)


@dataclass(frozen=True, slots=True)
class LLMResult:
    """Raw model text plus the usage of the call that produced it."""

    content: str
    usage: TokenUsage | None


class BaseLLMChain:  # noqa: B903 - base class for subclasses, not a data holder
    def __init__(self, model: AsyncChatModel, model_name: str = "unknown") -> None:
        self._model = model
        self._model_name = model_name

    async def _invoke(self, messages: list[BaseMessage]) -> LLMResult:
        started = time.perf_counter()
        try:
            response = await self._model.ainvoke(messages)
        except Exception as exc:
            error = self._error_for_exception(exc)
            error.token_usages = [self._usage_from_exception(exc, error.code, started)]
            raise error from exc
        if not isinstance(response.content, str):
            raise InvalidModelOutputError([
                self._failed_usage(AgentErrorCode.INVALID_OUTPUT, started)
            ])
        latency_ms = int((time.perf_counter() - started) * 1000)
        return LLMResult(response.content.strip(), self._extract_usage(response, latency_ms))

    async def _invoke_validated(
        self,
        messages: list[BaseMessage],
        turn_type: type[TurnT],
        validator: Callable[[str], TurnT] | None = None,
    ) -> tuple[TurnT, list[TokenUsage]]:
        """Invoke the model and validate its JSON, repairing once if needed.

        The malformed first call still consumed tokens, so its usage is kept and
        re-tagged with ``llm_invalid_output`` instead of being discarded.

        ``validator`` lets a caller add per-request checks Pydantic cannot make
        on its own. It is passed in rather than held on the instance because the
        chains are cached singletons shared by concurrent requests. It must
        raise ``ValidationError`` on rejection so the repair path fires.
        """
        validate = validator or (lambda raw: turn_type.model_validate_json(raw))
        result = await self._invoke(messages)
        token_usages = [result.usage] if result.usage is not None else []
        try:
            return validate(result.content), token_usages
        except ValidationError as validation_error:
            logger.debug(
                "%s result invalid; raw model output: %s", turn_type.__name__, result.content
            )
            logger.debug("%s validation error: %s", turn_type.__name__, validation_error)
            # `except ... as` borra el nombre al salir del bloque: se copia aqui.
            repair_hint = str(validation_error)
            if result.usage is not None:
                token_usages[0] = replace(result.usage, status=AgentErrorCode.INVALID_OUTPUT.value)

        logger.debug("%s result was invalid; requesting a repair", turn_type.__name__)
        try:
            repair = await self._invoke(
                self._repair_messages(result.content, turn_type, repair_hint)
            )
        except AgentError as error:
            error.token_usages = [*token_usages, *error.token_usages]
            raise
        if repair.usage is not None:
            token_usages.append(repair.usage)
        logger.debug("%s repair result: %s", turn_type.__name__, repair.content)
        try:
            return validate(repair.content), token_usages
        except ValidationError as repair_error:
            if repair.usage is not None:
                token_usages[-1] = replace(repair.usage, status=AgentErrorCode.INVALID_OUTPUT.value)
            logger.debug("%s repaired result still invalid: %s", turn_type.__name__, repair_error)
            raise InvalidModelOutputError(token_usages) from repair_error

    @staticmethod
    def _repair_messages(raw_result: str, turn_type: type[TurnT], errors: str) -> list[BaseMessage]:
        """El esquema solo no basta: sin los errores concretos el modelo tiene que
        encontrar el fallo por su cuenta en un JSON grande, y suele repetirlo."""
        return [
            SystemMessage(
                content=(
                    "Return only a valid JSON object matching this JSON schema. Do not return "
                    f"Markdown or prose. Schema: {turn_type.model_json_schema()}. "
                    "Fix exactly these validation errors, leaving every valid field untouched:\n"
                    f"{errors}"
                )
            ),
            HumanMessage(content=raw_result),
        ]

    def _usage_from_exception(
        self, exc: Exception, code: AgentErrorCode, started: float
    ) -> TokenUsage:
        """Real counts when the provider attached them to the exception.

        ``LengthFinishReasonError`` carries the completion that exhausted the
        budget: esos tokens se facturaron, asi que registrar ceros ocultaria los
        fallos mas caros al coste y al limitador de consumo. ``reasoning_tokens``
        solo se registra en el log: va dentro de ``completion_tokens`` y sumarlo
        en otro campo seria contarlo dos veces.
        """
        usage = getattr(getattr(exc, "completion", None), "usage", None)
        if usage is None:
            return self._failed_usage(code, started)

        details = getattr(usage, "completion_tokens_details", None)
        logger.warning(
            "%s con consumo real: prompt=%s completion=%s (razonamiento=%s) total=%s",
            code.value,
            usage.prompt_tokens,
            usage.completion_tokens,
            getattr(details, "reasoning_tokens", "?"),
            usage.total_tokens,
        )
        return TokenUsage(
            model=self._model_name,
            prompt_tokens=usage.prompt_tokens or 0,
            completion_tokens=usage.completion_tokens or 0,
            total_tokens=usage.total_tokens or 0,
            status=code.value,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def _failed_usage(self, code: AgentErrorCode, started: float) -> TokenUsage:
        return TokenUsage(
            model=self._model_name,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            status=code.value,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

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
    def _error_for_exception(error: Exception) -> AgentError:
        if isinstance(error, openai.LengthFinishReasonError):
            return AgentError(AgentErrorCode.OUTPUT_LIMIT, retryable=True)
        if isinstance(error, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return AgentError(AgentErrorCode.AUTHENTICATION, retryable=False)
        if isinstance(error, openai.RateLimitError):
            return AgentError(AgentErrorCode.RATE_LIMITED, retryable=True)
        if isinstance(error, openai.BadRequestError):
            return AgentError(AgentErrorCode.INVALID_REQUEST, retryable=False)
        if isinstance(error, (openai.APITimeoutError, httpx.TimeoutException, TimeoutError)):
            return AgentError(AgentErrorCode.TIMEOUT, retryable=True)
        if isinstance(error, openai.APIConnectionError):
            return AgentError(AgentErrorCode.UNAVAILABLE, retryable=True)
        if isinstance(error, openai.APIStatusError):
            return BaseLLMChain._status_error(error)
        return AgentError(AgentErrorCode.UNAVAILABLE, retryable=True)

    @staticmethod
    def _status_error(error: openai.APIStatusError) -> AgentError:
        if error.status_code in {401, 403}:
            return AgentError(AgentErrorCode.AUTHENTICATION, retryable=False)
        if error.status_code == 402:
            return AgentError(AgentErrorCode.QUOTA, retryable=False)
        if error.status_code == 429:
            return AgentError(AgentErrorCode.RATE_LIMITED, retryable=True)
        if error.status_code in {400, 422}:
            return AgentError(AgentErrorCode.INVALID_REQUEST, retryable=False)
        if error.status_code == 408:
            return AgentError(AgentErrorCode.TIMEOUT, retryable=True)
        if error.status_code >= 500:
            return AgentError(AgentErrorCode.UNAVAILABLE, retryable=True)
        return AgentError(AgentErrorCode.UNAVAILABLE, retryable=True)

    @staticmethod
    def _to_langchain_messages(history: Sequence[ConversationMessage]) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        for message in history:
            if message.role == "user":
                messages.append(HumanMessage(content=message.content))
            else:
                messages.append(AIMessage(content=message.content))
        return messages
