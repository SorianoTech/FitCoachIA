import pytest
from pydantic import ValidationError

from fitcoach.infrastructure.config.settings import Settings


class TestSettingsBotTelegramCommands:
    def test_parses_comma_separated_name_description_pairs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("bot_telegram_token", "test-token")
        monkeypatch.setenv("bot_telegram_url", "http://test-telegram:9999")
        monkeypatch.setenv("bot_telegram_commands", "a:desc a,b:desc b")

        settings = Settings(_env_file=None)

        assert settings.bot_telegram_commands == ["a:desc a", "b:desc b"]

    def test_strips_whitespace_and_ignores_trailing_comma(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("bot_telegram_token", "test-token")
        monkeypatch.setenv("bot_telegram_url", "http://test-telegram:9999")
        monkeypatch.setenv("bot_telegram_commands", " a:x , b:y ,")

        settings = Settings(_env_file=None)

        assert settings.bot_telegram_commands == ["a:x", "b:y"]

    def test_missing_commands_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("bot_telegram_token", "test-token")
        monkeypatch.setenv("bot_telegram_url", "http://test-telegram:9999")
        monkeypatch.delenv("bot_telegram_commands", raising=False)

        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_missing_token_raises_validation_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("bot_telegram_url", "http://test-telegram:9999")
        monkeypatch.setenv("bot_telegram_commands", "a:desc a")
        monkeypatch.delenv("bot_telegram_token", raising=False)

        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_missing_url_raises_validation_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("bot_telegram_token", "test-token")
        monkeypatch.setenv("bot_telegram_commands", "a:desc a")
        monkeypatch.delenv("bot_telegram_url", raising=False)

        with pytest.raises(ValidationError):
            Settings(_env_file=None)
