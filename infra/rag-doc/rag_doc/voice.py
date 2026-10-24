"""Speech adapters: OpenAI/faster-whisper (speech to text) and Piper (text to speech)."""

import io
import logging
import wave
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class VoiceError(Exception):
    """Base error of the voice adapters."""


class AudioTooLongError(VoiceError):
    pass


class SpeechRecognitionError(VoiceError):
    pass


class SpeechSynthesisError(VoiceError):
    pass


class SpeechToText(Protocol):
    def transcribe(self, audio: bytes) -> str: ...


class TextToSpeech(Protocol):
    def synthesize(self, text: str) -> bytes: ...


class WhisperTranscriber:
    def __init__(self, model_name: str, model_dir: str, max_seconds: float) -> None:
        from faster_whisper import WhisperModel  # lazy: heavy import, not needed by unit tests

        self._model = WhisperModel(
            model_name, device="cpu", compute_type="int8", download_root=model_dir
        )
        self._max_seconds = max_seconds

    def transcribe(self, audio: bytes) -> str:
        try:
            segments, info = self._model.transcribe(
                io.BytesIO(audio), language="es", vad_filter=True
            )
            # Duration is known before decoding, so over-long audio is rejected cheaply
            if info.duration > self._max_seconds:
                raise AudioTooLongError(f"audio of {info.duration:.0f}s")
            return " ".join(segment.text.strip() for segment in segments).strip()
        except VoiceError:
            raise
        except Exception as exc:
            raise SpeechRecognitionError("could not decode the audio") from exc


def _audio_filename(audio: bytes) -> str:
    # The API infers the container from the file extension, so sniff it from the magic bytes
    if audio[:4] == b"\x1a\x45\xdf\xa3":
        return "audio.webm"
    if audio[:4] == b"OggS":
        return "audio.ogg"
    if audio[4:8] == b"ftyp":
        return "audio.mp4"
    if audio[:4] == b"RIFF":
        return "audio.wav"
    return "audio.webm"


class CloudTranscriber:
    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    def transcribe(self, audio: bytes) -> str:
        try:
            result = self._client.audio.transcriptions.create(
                model=self._model, file=(_audio_filename(audio), audio), language="es"
            )
        except Exception as exc:
            raise SpeechRecognitionError("cloud transcription failed") from exc
        return str(result.text).strip()


class FallbackTranscriber:
    def __init__(self, primary: SpeechToText, fallback: SpeechToText) -> None:
        self._primary = primary
        self._fallback = fallback

    def transcribe(self, audio: bytes) -> str:
        try:
            return self._primary.transcribe(audio)
        except SpeechRecognitionError:
            logger.warning("primary transcription failed, using the local fallback", exc_info=True)
            return self._fallback.transcribe(audio)


class PiperSynthesizer:
    def __init__(self, voice_path: str) -> None:
        from piper import PiperVoice  # lazy: heavy import, not needed by unit tests

        self._voice = PiperVoice.load(voice_path)

    def synthesize(self, text: str) -> bytes:
        buffer = io.BytesIO()
        try:
            with wave.open(buffer, "wb") as wav_file:
                self._voice.synthesize_wav(text, wav_file)
        except Exception as exc:
            raise SpeechSynthesisError("could not synthesize the text") from exc
        return buffer.getvalue()
