import pytest

from fitcoach.service.word_counter_service import (
    EmptyMessageError,
    MessageTooLongError,
    WordCounterService,
)


class TestWordCounterService:
    def setup_method(self) -> None:
        self.service = WordCounterService()

    def test_returns_unique_word_when_message_has_one_word(self) -> None:
        assert self.service.most_repeated_word("hello") == "hello"

    def test_returns_most_repeated_word(self) -> None:
        message = "hello world hello python world hello"
        assert self.service.most_repeated_word(message) == "hello"

    def test_is_case_insensitive(self) -> None:
        message = "Hello hello HELLO world"
        assert self.service.most_repeated_word(message) == "hello"

    def test_ignores_punctuation(self) -> None:
        message = "fit, fit! coach. coach? fit;"
        assert self.service.most_repeated_word(message) == "fit"

    def test_returns_first_word_when_tie(self) -> None:
        # En empate, Counter.most_common preserva orden de aparición.
        message = "alpha beta"
        assert self.service.most_repeated_word(message) == "alpha"

    def test_accepts_message_with_exactly_max_length(self) -> None:
        message = "word " * 50  # 250 chars exactos
        assert len(message) == WordCounterService.MAX_LENGTH
        assert self.service.most_repeated_word(message) == "word"

    def test_raises_when_message_is_none(self) -> None:
        with pytest.raises(EmptyMessageError):
            self.service.most_repeated_word(None)

    def test_raises_when_message_is_empty_string(self) -> None:
        with pytest.raises(EmptyMessageError):
            self.service.most_repeated_word("")

    def test_raises_when_message_is_only_whitespace(self) -> None:
        with pytest.raises(EmptyMessageError):
            self.service.most_repeated_word("   \t\n  ")

    def test_raises_when_message_has_no_words_only_symbols(self) -> None:
        with pytest.raises(EmptyMessageError):
            self.service.most_repeated_word("!!! ??? ...")

    def test_raises_when_message_exceeds_max_length(self) -> None:
        message = "a" * (WordCounterService.MAX_LENGTH + 1)
        with pytest.raises(MessageTooLongError):
            self.service.most_repeated_word(message)
