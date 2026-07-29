"""Integration tests for the fail-fast Telegram config check in fitcoach.main.lifespan."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import fitcoach.main as main_module
from fitcoach.infrastructure.config.settings import Settings
from fitcoach.main import app


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    main_module.get_settings.cache_clear()
    yield
    main_module.get_settings.cache_clear()


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> None:
    """Bypass any local .env file so these tests are deterministic in dev and CI."""
    monkeypatch.setattr(main_module, "get_settings", lambda: Settings(_env_file=None, **kwargs))


class TestStartupFailFast:
    def test_starts_successfully_with_valid_telegram_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(
            monkeypatch,
            bot_telegram_token="test-token",  # noqa: S106
            bot_telegram_url="http://test-telegram:9999",
            bot_telegram_commands=["start:Inicia FitCoach"],
        )

        with TestClient(app) as client:
            response = client.get("/health")

        assert response.status_code == 200

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

    def test_fails_to_start_when_a_command_pair_is_malformed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_settings(
            monkeypatch,
            bot_telegram_token="test-token",  # noqa: S106
            bot_telegram_url="http://test-telegram:9999",
            bot_telegram_commands=["start"],  # missing ":description"
        )

        with pytest.raises(ValueError, match="Invalid Telegram command"), TestClient(app):
            pass
