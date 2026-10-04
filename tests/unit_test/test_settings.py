from datetime import timedelta

import pytest
from pydantic import ValidationError

from fitcoach.infrastructure.config.settings import (
    DatabaseSettings,
    EmbedderSettings,
    EvaluationSettings,
    IASettings,
    Settings,
    TrainingSettings,
    UsageSettings,
    VectorDatabaseSettings,
)


def _set_valid_bot_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("bot_telegram_token", "test-token")
    monkeypatch.setenv("bot_telegram_url", "http://test-telegram:9999")
    monkeypatch.setenv("bot_telegram_commands", "a:desc a")
    monkeypatch.setenv("bot_telegram_secret_token", "test-secret-token")
    monkeypatch.setenv("bot_telegram_webhook_base_url", "https://example.com")


class TestSettingsBotTelegramCommands:
    def test_parses_comma_separated_name_description_pairs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_valid_bot_env(monkeypatch)
        monkeypatch.setenv("bot_telegram_commands", "a:desc a,b:desc b")

        settings = Settings(_env_file=None)

        assert settings.bot_telegram_commands == ["a:desc a", "b:desc b"]

    def test_strips_whitespace_and_ignores_trailing_comma(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_valid_bot_env(monkeypatch)
        monkeypatch.setenv("bot_telegram_commands", "a:desc a,b:desc b")

        settings = Settings(_env_file=None)

        assert settings.bot_telegram_commands == ["a:desc a", "b:desc b"]

    def test_missing_commands_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("bot_telegram_token", "test-token")
        monkeypatch.setenv("bot_telegram_url", "http://test-telegram:9999")
        monkeypatch.delenv("bot_telegram_commands", raising=False)

        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_missing_token_raises_validation_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_valid_bot_env(monkeypatch)
        monkeypatch.delenv("bot_telegram_token", raising=False)

        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_missing_url_raises_validation_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("bot_telegram_token", "test-token")
        monkeypatch.setenv("bot_telegram_commands", "a:desc a")
        monkeypatch.delenv("bot_telegram_url", raising=False)

        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_missing_secret_token_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_valid_bot_env(monkeypatch)
        monkeypatch.delenv("bot_telegram_secret_token", raising=False)

        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_rejects_a_secret_token_with_invalid_characters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_valid_bot_env(monkeypatch)
        monkeypatch.setenv("bot_telegram_secret_token", "con espacios y ñ")

        with pytest.raises(ValidationError):
            Settings(_env_file=None)

    def test_parses_and_deduplicates_exercise_moderator_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_valid_bot_env(monkeypatch)
        monkeypatch.setenv("bot_telegram_exercise_admin_ids", "9, 3, 9")

        settings = Settings(_env_file=None)

        assert settings.bot_telegram_exercise_admin_ids == [3, 9]


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
        monkeypatch.setenv(
            "vector_database_url", "postgresql+asyncpg://ro:pwd@pgvector:5432/fitcoach"
        )

        settings = VectorDatabaseSettings(_env_file=None)

        assert settings.url == "postgresql+asyncpg://ro:pwd@pgvector:5432/fitcoach"

    def test_missing_url_raises_validation_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("vector_database_url", raising=False)

        with pytest.raises(ValidationError):
            VectorDatabaseSettings(_env_file=None)

    def test_writer_url_is_optional_and_configurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("vector_database_url", "postgresql+asyncpg://reader@db/catalogue")
        monkeypatch.delenv("vector_database_writer_url", raising=False)

        assert VectorDatabaseSettings(_env_file=None).writer_url is None

        monkeypatch.setenv("vector_database_writer_url", "postgresql+asyncpg://writer@db/catalogue")
        assert (
            VectorDatabaseSettings(_env_file=None).writer_url
            == "postgresql+asyncpg://writer@db/catalogue"
        )


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


class TestUsageSettings:
    def test_works_without_any_configuration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Las tres variables son opcionales: sin ellas la cuota sigue activa."""
        for name in (
            "rate_limit_token_limit",
            "rate_limit_soft_ratio",
            "rate_limit_window_minutes",
        ):
            monkeypatch.delenv(name, raising=False)

        limits = UsageSettings(_env_file=None).to_limits()

        assert limits.hard_tokens == 150_000
        assert limits.soft_tokens == 99_000
        assert limits.window == timedelta(hours=24)

    def test_the_default_gap_fits_a_whole_interview(self) -> None:
        """Invariante de la calibracion: quien arranca una entrevista puede terminarla."""
        limits = UsageSettings(_env_file=None).to_limits()

        assert limits.hard_tokens - limits.soft_tokens >= 50_000

    def test_derives_the_soft_threshold_from_the_ratio(self) -> None:
        limits = UsageSettings(_env_file=None, token_limit=200_000, soft_ratio=0.5).to_limits()

        assert limits.hard_tokens == 200_000
        assert limits.soft_tokens == 100_000

    def test_a_ratio_of_one_collapses_both_thresholds(self) -> None:
        """Interruptor para desactivar el corte escalonado sin tocar codigo."""
        limits = UsageSettings(_env_file=None, token_limit=1_000, soft_ratio=1.0).to_limits()

        assert limits.soft_tokens == limits.hard_tokens

    def test_window_minutes_becomes_a_timedelta(self) -> None:
        limits = UsageSettings(_env_file=None, window_minutes=720).to_limits()

        assert limits.window == timedelta(hours=12)

    def test_accepts_a_window_shorter_than_an_hour(self) -> None:
        """Dev necesita ventanas cortas para poder probar el corte sin esperar."""
        limits = UsageSettings(_env_file=None, window_minutes=5).to_limits()

        assert limits.window == timedelta(minutes=5)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("token_limit", 0),
            ("token_limit", -1),
            ("soft_ratio", 0.0),
            ("soft_ratio", 1.5),
            ("window_minutes", 0),
        ],
    )
    def test_rejects_values_that_would_disable_or_invert_the_quota(
        self, field: str, value: float
    ) -> None:
        # Un ratio de 0 cortaria desde el primer mensaje; uno mayor que 1 nunca cortaria.
        with pytest.raises(ValidationError):
            UsageSettings(_env_file=None, **{field: value})


class TestTrainingSettings:
    def test_defaults_reproduce_the_previous_hardcoded_policy(self) -> None:
        policy = TrainingSettings(_env_file=None).to_retry_policy()

        assert policy.max_attempts == 5
        assert policy.retry_delay == timedelta(seconds=30)
        assert policy.retry_max_delay == timedelta(seconds=3600)
        assert policy.sending_timeout == timedelta(seconds=120)
        assert policy.batch_size == 100

    def test_keeps_reading_the_existing_variable_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("training_reminders_enabled", "true")
        monkeypatch.setenv("training_reminder_interval_seconds", "60")
        monkeypatch.setenv("training_reminder_max_attempts", "3")

        settings = TrainingSettings(_env_file=None)

        assert settings.reminders_enabled
        assert settings.interval_seconds == 60
        assert settings.max_attempts == 3

    def test_reads_the_new_retry_variables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("training_reminder_retry_delay_seconds", "15")
        monkeypatch.setenv("training_reminder_sending_timeout_seconds", "60")

        policy = TrainingSettings(_env_file=None).to_retry_policy()

        assert policy.retry_delay == timedelta(seconds=15)
        assert policy.sending_timeout == timedelta(seconds=60)

    def test_reminders_are_disabled_without_configuration(self) -> None:
        assert not TrainingSettings(_env_file=None).reminders_enabled


class TestEvaluationSettings:
    def test_is_disabled_without_configuration(self) -> None:
        assert not EvaluationSettings(_env_file=None).enabled

    def test_reads_the_retry_policy_from_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("evaluation_retry_delay_seconds", "10")
        monkeypatch.setenv("evaluation_retry_max_delay_seconds", "600")

        policy = EvaluationSettings(_env_file=None).to_retry_policy()

        assert policy.retry_delay == timedelta(seconds=10)
        assert policy.retry_max_delay == timedelta(seconds=600)

    def test_rejects_a_max_delay_below_the_initial_delay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("evaluation_retry_delay_seconds", "100")
        monkeypatch.setenv("evaluation_retry_max_delay_seconds", "50")

        with pytest.raises(ValidationError):
            EvaluationSettings(_env_file=None)

    @pytest.mark.parametrize(
        ("variable", "value"),
        [
            ("evaluation_interval_seconds", "5"),
            ("evaluation_max_attempts", "0"),
            ("evaluation_sending_timeout_seconds", "1"),
            ("evaluation_batch_size", "0"),
        ],
    )
    def test_rejects_out_of_range_values(
        self, monkeypatch: pytest.MonkeyPatch, variable: str, value: str
    ) -> None:
        monkeypatch.setenv(variable, value)

        with pytest.raises(ValidationError):
            EvaluationSettings(_env_file=None)
