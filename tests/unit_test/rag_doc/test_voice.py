import io
import wave
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rag_doc.api import router
from rag_doc.limits import RateLimiter
from rag_doc.texts import MAX_AUDIO_BYTES, MAX_TTS_CHARS
from rag_doc.voice import (
    AudioTooLongError,
    PiperSynthesizer,
    SpeechRecognitionError,
    SpeechSynthesisError,
    WhisperTranscriber,
)


class FakeSTT:
    def __init__(self, text: str = "hola", error: Exception | None = None) -> None:
        self.text, self.error, self.received = text, error, b""

    def transcribe(self, audio: bytes) -> str:
        self.received = audio
        if self.error:
            raise self.error
        return self.text


class FakeTTS:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def synthesize(self, text: str) -> bytes:
        if self.error:
            raise self.error
        return b"RIFFfake"


def _client(stt: FakeSTT | None = None, tts: FakeTTS | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.stt = stt or FakeSTT()
    app.state.tts = tts or FakeTTS()
    app.state.rate_limiter = RateLimiter(per_minute=1000, daily_cap=1000)
    return TestClient(app)


def _post_audio(client: TestClient, data: bytes = b"audio", ctype: str = "audio/webm"):
    return client.post("/api/stt", content=data, headers={"Content-Type": ctype})


def test_stt_returns_the_transcription() -> None:
    stt = FakeSTT("qué es el scheduler")

    response = _post_audio(_client(stt), b"bytes")

    assert response.status_code == 200
    assert response.json() == {"text": "qué es el scheduler"}
    assert stt.received == b"bytes"


def test_stt_rejects_non_audio_content_type() -> None:
    assert _post_audio(_client(), ctype="application/json").status_code == 415


def test_stt_rejects_empty_body() -> None:
    assert _post_audio(_client(), b"").status_code == 422


def test_stt_rejects_oversized_audio() -> None:
    response = _post_audio(_client(), b"x" * (MAX_AUDIO_BYTES + 1))

    assert response.status_code == 413


def test_stt_maps_too_long_audio_to_413() -> None:
    assert _post_audio(_client(FakeSTT(error=AudioTooLongError("60s")))).status_code == 413


def test_stt_maps_undecodable_audio_to_422() -> None:
    assert _post_audio(_client(FakeSTT(error=SpeechRecognitionError("bad")))).status_code == 422


def test_stt_rejects_silence_without_text() -> None:
    assert _post_audio(_client(FakeSTT(text=""))).status_code == 422


def test_tts_returns_wav_audio() -> None:
    response = _client().post("/api/tts", json={"text": "hola"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == b"RIFFfake"


def test_tts_rejects_too_long_and_blank_text() -> None:
    client = _client()

    assert client.post("/api/tts", json={"text": "a" * (MAX_TTS_CHARS + 1)}).status_code == 422
    assert client.post("/api/tts", json={"text": "   "}).status_code == 422


def test_tts_maps_synthesis_failure_to_500() -> None:
    client = _client(tts=FakeTTS(error=SpeechSynthesisError("boom")))

    assert client.post("/api/tts", json={"text": "hola"}).status_code == 500


def _transcriber(duration: float, texts: list[str], max_seconds: float = 30.0):
    model = SimpleNamespace(
        transcribe=lambda *_a, **_k: (
            iter([SimpleNamespace(text=f" {t} ") for t in texts]),
            SimpleNamespace(duration=duration),
        )
    )
    transcriber = WhisperTranscriber.__new__(WhisperTranscriber)
    transcriber._model = model
    transcriber._max_seconds = max_seconds
    return transcriber


def test_whisper_joins_segments() -> None:
    assert _transcriber(5, ["hola", "mundo"]).transcribe(b"a") == "hola mundo"


def test_whisper_rejects_audio_longer_than_limit() -> None:
    with pytest.raises(AudioTooLongError):
        _transcriber(31, ["x"]).transcribe(b"a")


def test_whisper_wraps_decoder_failures() -> None:
    transcriber = _transcriber(1, [])

    def boom(*_a, **_k):
        raise ValueError("invalid data")

    transcriber._model = SimpleNamespace(transcribe=boom)
    with pytest.raises(SpeechRecognitionError):
        transcriber.transcribe(b"a")


def test_piper_writes_a_valid_wav() -> None:
    def synthesize_wav(text: str, wav_file: wave.Wave_write) -> None:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 100)

    synthesizer = PiperSynthesizer.__new__(PiperSynthesizer)
    synthesizer._voice = SimpleNamespace(synthesize_wav=synthesize_wav)

    with wave.open(io.BytesIO(synthesizer.synthesize("hola"))) as wav_file:
        assert wav_file.getnframes() == 100


def test_piper_wraps_failures() -> None:
    def boom(*_a, **_k):
        raise RuntimeError("no voice")

    synthesizer = PiperSynthesizer.__new__(PiperSynthesizer)
    synthesizer._voice = SimpleNamespace(synthesize_wav=boom)

    with pytest.raises(SpeechSynthesisError):
        synthesizer.synthesize("hola")
