import pytest
from pydantic import ValidationError

from fitcoach.infrastructure.config.settings import IASettings, get_ia_settings


class TestIASettings:
    def test_loads_required_fields_and_integer_defaults_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ia_base_url", "http://test-llm:9999")
        monkeypatch.setenv("ia_token", "test-token")
        monkeypatch.setenv("ia_model", "test-model")
        monkeypatch.setenv("ia_temperature", "0.5")

        settings = IASettings(_env_file=None)

        assert settings.base_url == "http://test-llm:9999"
        assert settings.token == "test-token"  # noqa: S105
        assert settings.model == "test-model"
        assert settings.temperature == 0.5
        assert settings.timeout_seconds == 0
        assert settings.max_tokens == 0

    def test_explicit_integer_env_vars_override_the_zero_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ia_base_url", "http://test-llm:9999")
        monkeypatch.setenv("ia_token", "test-token")
        monkeypatch.setenv("ia_model", "test-model")
        monkeypatch.setenv("ia_temperature", "0.5")
        monkeypatch.setenv("ia_timeout_seconds", "30")
        monkeypatch.setenv("ia_max_tokens", "128")

        settings = IASettings(_env_file=None)

        assert settings.timeout_seconds == 30
        assert settings.max_tokens == 128

    def test_missing_token_raises_validation_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ia_base_url", "http://test-llm:9999")
        monkeypatch.setenv("ia_model", "test-model")
        monkeypatch.setenv("ia_temperature", "0.5")
        monkeypatch.delenv("ia_token", raising=False)

        with pytest.raises(ValidationError):
            IASettings(_env_file=None)

    def test_missing_base_url_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ia_token", "test-token")
        monkeypatch.setenv("ia_model", "test-model")
        monkeypatch.setenv("ia_temperature", "0.5")
        monkeypatch.delenv("ia_base_url", raising=False)

        with pytest.raises(ValidationError):
            IASettings(_env_file=None)

    def test_get_ia_settings_returns_a_cached_singleton(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ia_base_url", "http://test-llm:9999")
        monkeypatch.setenv("ia_token", "test-token")
        monkeypatch.setenv("ia_model", "test-model")
        monkeypatch.setenv("ia_temperature", "0.5")
        get_ia_settings.cache_clear()

        try:
            first = get_ia_settings()
            second = get_ia_settings()

            assert first is second
        finally:
            get_ia_settings.cache_clear()
