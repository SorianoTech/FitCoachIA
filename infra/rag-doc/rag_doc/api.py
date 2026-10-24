"""HTTP API: text questions."""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from rag_doc.limits import enforce_limits
from rag_doc.llm import LLMError
from rag_doc.service import AnswerService
from rag_doc.texts import (
    AUDIO_INVALID_ANSWER,
    AUDIO_TOO_LARGE_ANSWER,
    LLM_UNAVAILABLE_ANSWER,
    MAX_AUDIO_BYTES,
    MAX_HISTORY_CHARS,
    MAX_HISTORY_TURNS,
    MAX_QUESTION_CHARS,
    MAX_TTS_CHARS,
    NO_SPEECH_ANSWER,
    TTS_FAILED_ANSWER,
)
from rag_doc.voice import (
    AudioTooLongError,
    SpeechRecognitionError,
    SpeechSynthesisError,
    SpeechToText,
    TextToSpeech,
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


def get_stt(request: Request) -> SpeechToText:
    stt: SpeechToText = request.app.state.stt
    return stt


def get_tts(request: Request) -> TextToSpeech:
    tts: TextToSpeech = request.app.state.tts
    return tts


class TranscriptionResponse(BaseModel):
    text: str


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TTS_CHARS)


@router.post("/stt", dependencies=[Depends(enforce_limits)])
async def speech_to_text(
    request: Request, stt: SpeechToText = Depends(get_stt)
) -> TranscriptionResponse:
    audio = await _read_audio(request)
    try:
        text = await asyncio.to_thread(stt.transcribe, audio)
    except AudioTooLongError as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, AUDIO_TOO_LARGE_ANSWER) from exc
    except SpeechRecognitionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, AUDIO_INVALID_ANSWER) from exc
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, NO_SPEECH_ANSWER)
    return TranscriptionResponse(text=text[:MAX_QUESTION_CHARS])


@router.post("/tts", dependencies=[Depends(enforce_limits)])
async def text_to_speech(body: SpeakRequest, tts: TextToSpeech = Depends(get_tts)) -> Response:
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "El texto está vacío")
    try:
        wav = await asyncio.to_thread(tts.synthesize, text)
    except SpeechSynthesisError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, TTS_FAILED_ANSWER) from exc
    return Response(content=wav, media_type="audio/wav")


async def _read_audio(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_AUDIO_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, AUDIO_TOO_LARGE_ANSWER)
    if not request.headers.get("content-type", "").startswith("audio/"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, AUDIO_INVALID_ANSWER)
    audio = bytearray()
    async for chunk in request.stream():
        audio += chunk
        if len(audio) > MAX_AUDIO_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, AUDIO_TOO_LARGE_ANSWER)
    if not audio:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, AUDIO_INVALID_ANSWER)
    return bytes(audio)


@router.post("/ask", dependencies=[Depends(enforce_limits)])
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
