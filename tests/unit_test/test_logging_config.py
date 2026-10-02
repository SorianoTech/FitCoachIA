import io
import logging
from collections.abc import Iterator

import pytest

from fitcoach.infrastructure.config.logging_config import (
    LoggingSettings,
    QualnameFormatter,
    configure_logging,
    get_logging_settings,
)


@pytest.fixture(autouse=True)
def _clear_logging_settings_cache() -> Iterator[None]:
    get_logging_settings.cache_clear()
    yield
    get_logging_settings.cache_clear()


@pytest.fixture
def _preserve_root_logger_state() -> Iterator[None]:
    """configure_logging() mutates the real root logger; snapshot and restore it."""
    root = logging.getLogger()
    previous_level = root.level
    previous_handlers = list(root.handlers)
    yield
    root.handlers = previous_handlers
    root.setLevel(previous_level)


def _module_level_handle() -> None:
    """Module-scoped on purpose: co_qualname has no enclosing class/test-method to prefix."""
    logging.getLogger("test.qualname.function").debug("live line")


class TestLoggingSettingsLevel:
    def test_defaults_to_info_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("log_level", raising=False)

        assert LoggingSettings(_env_file=None).level == "INFO"

    def test_reads_log_level_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("log_level", "DEBUG")

        assert LoggingSettings(_env_file=None).level == "DEBUG"

    def test_normalises_lowercase_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("log_level", "debug")

        assert LoggingSettings(_env_file=None).level == "DEBUG"

    def test_falls_back_to_info_on_invalid_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("log_level", "VERBOSE")

        assert LoggingSettings(_env_file=None).level == "INFO"

    def test_falls_back_to_info_on_empty_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("log_level", "")

        assert LoggingSettings(_env_file=None).level == "INFO"

    def test_get_logging_settings_returns_a_cached_singleton(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("log_level", "DEBUG")

        first = get_logging_settings()
        second = get_logging_settings()

        assert first is second


@pytest.mark.usefixtures("_preserve_root_logger_state")
class TestConfigureLogging:
    def test_sets_root_logger_to_the_configured_level(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("log_level", "DEBUG")
        logging.getLogger().handlers = []

        configure_logging()

        assert logging.getLogger().level == logging.DEBUG

    def test_is_a_noop_when_root_logger_already_has_handlers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("log_level", "DEBUG")
        existing_handler = logging.StreamHandler()
        logging.getLogger().handlers = [existing_handler]

        configure_logging()

        assert logging.getLogger().handlers == [existing_handler]


class TestQualnameFormatter:
    def _emit_and_capture(self, log: logging.Logger, emit: object) -> str:
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(QualnameFormatter("%(name)s.%(qualname)s - %(message)s"))
        log.propagate = False
        log.setLevel(logging.DEBUG)
        log.addHandler(handler)
        emit()
        return stream.getvalue()

    def test_resolves_class_and_method_at_emit_time(self) -> None:
        log = logging.getLogger("test.qualname.method")

        class Webhook:
            def handle(self) -> None:
                log.debug("live line")

        output = self._emit_and_capture(log, Webhook().handle)

        assert "Webhook.handle" in output

    def test_resolves_plain_function_without_a_spurious_class_prefix(self) -> None:
        log = logging.getLogger("test.qualname.function")

        output = self._emit_and_capture(log, _module_level_handle)

        assert "test.qualname.function._module_level_handle" in output

    def test_deferred_formatting_degrades_to_funcname_without_raising(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)
        log = logging.getLogger("test.qualname.deferred")

        class Webhook:
            def handle(self) -> None:
                log.debug("stored line")

        Webhook().handle()
        record = next(r for r in caplog.records if r.message == "stored line")

        rendered = QualnameFormatter("%(name)s.%(qualname)s - %(message)s").format(record)

        assert "stored line" in rendered
        assert "Webhook.handle" not in rendered
