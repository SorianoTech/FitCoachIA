from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from fitcoach.service.word_counter_service import (
    EmptyMessageError,
    MessageTooLongError,
    WordCounterService,
)

router = APIRouter()


class Request(BaseModel):
    message: str | None = Field(default=None, description="Message to analyze")


class Response(BaseModel):
    message: str
    most_repeated_word: str


def get_word_counter_service() -> WordCounterService:
    return WordCounterService()


@router.post("/test", response_model=Response)
async def analyze_message(
    payload: Request,
    service: WordCounterService = Depends(get_word_counter_service),
) -> Response:
    try:
        word = service.most_repeated_word(payload.message)
    except EmptyMessageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except MessageTooLongError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return Response(message=payload.message or "", most_repeated_word=word)
