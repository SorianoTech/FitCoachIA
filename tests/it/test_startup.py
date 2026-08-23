"""Integration tests for the fail-fast Telegram/IA config check in fitcoach.main.lifespan."""

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import fitcoach.main as main_module
from fitcoach.infrastructure.config.logging_config import get_logging_settings
from fitcoach.infrastructure.config.settings import IASettings, Settings
from fitcoach.main import app

_VALID_TELEGRAM_KWARGS: dict[str, object] = {
    "bot_telegram_token": "test-token",  # noqa: S106
    "bot_telegram_url": "http://test-telegram:9999",
    "bot_telegram_commands": ["start:Inicia FitCoach"],
}
_VALID_IA_KWARGS: dict[str, object] = {
    "base_url": "http://test-llm:9999",
    "token": "test-token",  # noqa: S106
    "model": "test-model",
    "temperature": 0.5,
}


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    main_module.get_settings.cache_clear()
    main_module.get_ia_settings.cache_clear()
    get_logging_settings.cache_clear()
    yield
    main_module.get_settings.cache_clear()
    main_module.get_ia_settings.cache_clear()
    get_logging_settings.cache_clear()


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> None:
    """Bypass any local .env file so these tests are deterministic in dev and CI."""
    monkeypatch.setattr(main_module, "get_settings", lambda: Settings(_env_file=None, **kwargs))


def _patch_ia_settings(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> None:
    """Bypass any local .env file so these tests are deterministic in dev and CI."""
    monkeypatch.setattr(
        main_module, "get_ia_settings", lambda: IASettings(_env_file=None, **kwargs)
    )


class TestStartupFailFast:
    def test_starts_successfully_with_valid_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_settings(monkeypatch, **_VALID_TELEGRAM_KWARGS)
        _patch_ia_settings(monkeypatch, **_VALID_IA_KWARGS)

        with TestClient(app) as client:
            response = client.get("/health")

        assert response.status_code == 200
        assert logging.getLogger().handlers, "lifespan must call configure_logging()"

    def test_fails_to_start_when_bot_telegram_token_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(
            monkeypatch,
            bot_telegram_url="http://test-telegram:9999",
            bot_telegram_commands=["start:Inicia FitCoach"],
        )

        with pytest.raises(ValidationError, match="bot_telegram_token"), TestClient(app):
            pass

    def test_fails_to_start_when_bot_telegram_url_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(
            monkeypatch,
            bot_telegram_token="test-token",  # noqa: S106
            bot_telegram_commands=["start:Inicia FitCoach"],
        )

        with pytest.raises(ValidationError, match="bot_telegram_url"), TestClient(app):
            pass

    def test_fails_to_start_when_ia_token_is_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_settings(monkeypatch, **_VALID_TELEGRAM_KWARGS)
        _patch_ia_settings(
            monkeypatch, base_url="http://test-llm:9999", model="test-model", temperature=0.5
        )

        with pytest.raises(ValidationError, match="token"), TestClient(app):
            pass

    def test_fails_to_start_when_ia_base_url_is_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(monkeypatch, **_VALID_TELEGRAM_KWARGS)
        _patch_ia_settings(monkeypatch, token="test-token", model="test-model", temperature=0.5)  # noqa: S106

        with pytest.raises(ValidationError, match="base_url"), TestClient(app):
            pass

    def test_fails_to_start_when_a_command_pair_is_malformed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(
            monkeypatch,
            bot_telegram_token="test-token",  # noqa: S106
            bot_telegram_url="http://test-telegram:9999",
            bot_telegram_commands=["start"],  # missing ":description"
        )
        _patch_ia_settings(monkeypatch, **_VALID_IA_KWARGS)

        with pytest.raises(ValueError, match="Invalid Telegram command"), TestClient(app):
            pass
