import logging
from collections.abc import Sequence
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
from fitcoach.infrastructure.config.settings import IASettings, get_ia_settings
from fitcoach.service.agent.agent_factory import build_interviewer_agent

logger = logging.getLogger(__name__)


class AsyncChatModel(Protocol):
    async def ainvoke(self, input: list[BaseMessage]) -> BaseMessage: ...


class InterviewerResultError(InterviewerError):
    def __init__(self) -> None:
        super().__init__(InterviewerErrorCode.INVALID_OUTPUT, retryable=True)


class InterviewerChain:
    def __init__(self, model: AsyncChatModel, skill_name: str = "interviewer") -> None:
        self._model = model
        self._agent = build_interviewer_agent(skill_name=skill_name)

    async def respond(
        self, user_message: str, history: Sequence[ConversationMessage]
    ) -> InterviewerTurn:
        messages = [
            SystemMessage(content=self._agent.insert_context()),
            *self._to_langchain_messages(history),
            HumanMessage(content=user_message),
        ]
        raw_result = await self._invoke(messages)
        try:
            return InterviewerTurn.model_validate_json(raw_result)
        except ValidationError:
            logger.warning("Interviewer result was invalid; requesting a repair")
            repaired_result = await self._invoke([
                SystemMessage(
                    content=(
                        "Return only a valid JSON object matching this JSON schema. Do not return "
                        f"Markdown or prose. Schema: {InterviewerTurn.model_json_schema()}. "
                        "Correct all missing, invalid, and inconsistent fields."
                    )
                ),
                HumanMessage(content=raw_result),
            ])
            try:
                return InterviewerTurn.model_validate_json(repaired_result)
            except ValidationError as repair_error:
                raise InterviewerResultError() from repair_error

    async def _invoke(self, messages: list[BaseMessage]) -> str:
        try:
            response = await self._model.ainvoke(messages)
        except openai.LengthFinishReasonError as exc:
            raise InterviewerError(InterviewerErrorCode.OUTPUT_LIMIT, retryable=True) from exc
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise InterviewerError(InterviewerErrorCode.AUTHENTICATION, retryable=False) from exc
        except openai.RateLimitError as exc:
            raise InterviewerError(InterviewerErrorCode.RATE_LIMITED, retryable=True) from exc
        except openai.BadRequestError as exc:
            raise InterviewerError(InterviewerErrorCode.INVALID_REQUEST, retryable=False) from exc
        except (openai.APITimeoutError, httpx.TimeoutException) as exc:
            raise InterviewerError(InterviewerErrorCode.TIMEOUT, retryable=True) from exc
        except openai.APIConnectionError as exc:
            raise InterviewerError(InterviewerErrorCode.UNAVAILABLE, retryable=True) from exc
        except TimeoutError as exc:
            raise InterviewerError(InterviewerErrorCode.TIMEOUT, retryable=True) from exc
        except openai.APIStatusError as exc:
            raise self._status_error(exc) from exc
        if not isinstance(response.content, str):
            raise InterviewerResultError()
        return response.content.strip()

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
    return InterviewerChain(_build_model(settings), skill_name=settings.skill)
