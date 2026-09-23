import pytest
from pydantic import ValidationError

from fitcoach.infrastructure.config.settings import (
    DatabaseSettings,
    EmbedderSettings,
    IASettings,
    Settings,
    VectorDatabaseSettings,
)


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


class TestTrainerIASettings:
    def _base_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ia_base_url", "http://llm:9999")
        monkeypatch.setenv("ia_token", "test-token")
        monkeypatch.setenv("ia_model", "test-model")
        monkeypatch.setenv("ia_temperature", "0.5")

    def test_defaults_cover_the_trainer_without_extra_configuration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._base_env(monkeypatch)
        for name in (
            "ia_trainer_skill",
            "ia_trainer_max_tokens",
            "ia_trainer_history_window_messages",
            "ia_rag_top_k",
        ):
            monkeypatch.delenv(name, raising=False)

        settings = IASettings(_env_file=None)

        assert settings.trainer_skill == "trainer"
        # El mesociclo completo no cabe en el max_tokens de la entrevista.
        assert settings.trainer_max_tokens == 4096
        assert settings.trainer_history_window_messages == 10
        assert settings.rag_top_k == 8

    def test_reads_the_trainer_overrides_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._base_env(monkeypatch)
        monkeypatch.setenv("ia_trainer_skill", "trainer-dev")
        monkeypatch.setenv("ia_trainer_max_tokens", "8192")
        monkeypatch.setenv("ia_rag_top_k", "3")

        settings = IASettings(_env_file=None)

        assert settings.trainer_skill == "trainer-dev"
        assert settings.trainer_max_tokens == 8192
        assert settings.rag_top_k == 3


class TestVectorDatabaseSettings:
    def test_reads_the_url_from_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("vector_db_url", "postgresql+asyncpg://ro:pwd@pgvector:5432/fitcoach")

        settings = VectorDatabaseSettings(_env_file=None)

        assert settings.url == "postgresql+asyncpg://ro:pwd@pgvector:5432/fitcoach"

    def test_missing_url_raises_validation_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("vector_db_url", raising=False)

        with pytest.raises(ValidationError):
            VectorDatabaseSettings(_env_file=None)


class TestEmbedderSettings:
    def test_reads_url_and_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("embedder_url", "http://embedder:8100")
        monkeypatch.setenv("embedder_timeout_seconds", "25")

        settings = EmbedderSettings(_env_file=None)

        assert settings.url == "http://embedder:8100"
        assert settings.timeout_seconds == 25

    def test_timeout_has_a_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("embedder_url", "http://embedder:8100")
        monkeypatch.delenv("embedder_timeout_seconds", raising=False)

        assert EmbedderSettings(_env_file=None).timeout_seconds == 10

    def test_missing_url_raises_validation_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("embedder_url", raising=False)

        with pytest.raises(ValidationError):
            EmbedderSettings(_env_file=None)
