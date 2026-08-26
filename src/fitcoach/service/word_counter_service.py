import re
from collections import Counter


class EmptyMessageError(ValueError):
    """Raised when the input message is empty or only whitespace."""


class MessageTooLongError(ValueError):
    """Raised when the input message exceeds the allowed length."""


class WordCounterService:
    MAX_LENGTH = 250
    _WORD_PATTERN = re.compile(r"\b\w+\b", flags=re.UNICODE)

    def most_repeated_word(self, message: str | None) -> str:
        validated = self._validate(message)
        words: list[str] = self._WORD_PATTERN.findall(validated.lower())
        if not words:
            raise EmptyMessageError("Message does not contain any word")
        word, _ = Counter(words).most_common(1)[0]
        return word

    def _validate(self, message: str | None) -> str:
        if message is None or not message.strip():
            raise EmptyMessageError("Message must not be empty")
        if len(message) > self.MAX_LENGTH:
            raise MessageTooLongError(
                f"Message length {len(message)} exceeds the maximum of {self.MAX_LENGTH}"
            )
        return message
