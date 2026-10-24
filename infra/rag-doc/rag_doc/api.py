"""HTTP API: text questions."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from rag_doc.llm import LLMError
from rag_doc.service import AnswerService
from rag_doc.texts import (
    LLM_UNAVAILABLE_ANSWER,
    MAX_HISTORY_CHARS,
    MAX_HISTORY_TURNS,
    MAX_QUESTION_CHARS,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_HISTORY_CHARS)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    history: list[Turn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)


class SourceOut(BaseModel):
    source: str
    heading: str
    score: float


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceOut]


def get_answer_service(request: Request) -> AnswerService:
    service: AnswerService = request.app.state.answer_service
    return service


@router.post("/ask")
async def ask(
    body: AskRequest, service: AnswerService = Depends(get_answer_service)
) -> AskResponse:
    question = body.question.strip()
    if not question:
        raise HTTPException(422, "La pregunta está vacía")
    history = [turn.model_dump() for turn in body.history]
    try:
        result = await service.ask(question, history)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, LLM_UNAVAILABLE_ANSWER) from exc
    return AskResponse(
        answer=result.answer,
        sources=[SourceOut(**vars(source)) for source in result.sources],
    )
