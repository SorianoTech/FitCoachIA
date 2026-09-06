import pytest
from pydantic import ValidationError

from fitcoach.infrastructure.config.settings import DatabaseSettings, IASettings, Settings


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


class TestIASettings:
    def test_defaults_history_window_to_twenty_messages(self) -> None:
        settings = IASettings(
            _env_file=None,
            base_url="http://test-llm:9999",
            token="test-token",  # noqa: S106
            model="test-model",
            temperature=0.5,
        )

        assert settings.history_window_messages == 20


class TestDatabaseSettings:
    def test_loads_database_url_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("database_url", "postgresql+asyncpg://user:pass@db:5432/fitcoach")

        settings = DatabaseSettings(_env_file=None)

        assert settings.url == "postgresql+asyncpg://user:pass@db:5432/fitcoach"
