"""Speech adapters: faster-whisper (speech to text) and Piper (text to speech), CPU only."""

import io
import wave
from typing import Protocol


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
