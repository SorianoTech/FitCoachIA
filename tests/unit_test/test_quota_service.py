from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from fitcoach.domain.quota import (
    GLOBAL_SCOPE_ID,
    QuotaAction,
    QuotaAuditEntry,
    QuotaConfig,
    QuotaSettingsView,
    QuotaSource,
    resolve_quota,
)
from fitcoach.infrastructure.config.settings import UsageSettings
from fitcoach.service.quota_service import QuotaService

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
DEFAULTS = QuotaConfig(token_limit=150_000, soft_ratio=0.66, window_minutes=1_440)
GLOBAL = QuotaConfig(token_limit=1_000, soft_ratio=0.5, window_minutes=60)
USER = QuotaConfig(token_limit=500, soft_ratio=1.0, window_minutes=10)


class FakeQuotaRepository:
    def __init__(self) -> None:
        self.configs: dict[int, QuotaConfig] = {}
        self.usage: list[tuple[int, datetime, int]] = []
        self.known: set[int] = set()
        self.entries: list[QuotaAuditEntry] = []

    async def get_configs(self, chat_ids: list[int]) -> dict[int, QuotaConfig]:
        return {key: value for key, value in self.configs.items() if key in chat_ids}

    async def save_config(
        self, actor_chat_id: int, scope_id: int, config: QuotaConfig, action: QuotaAction
    ) -> None:
        self._log(actor_chat_id, scope_id, action, self.configs.get(scope_id), config)
        self.configs[scope_id] = config

    async def delete_config(self, actor_chat_id: int, scope_id: int, action: QuotaAction) -> None:
        self._log(actor_chat_id, scope_id, action, self.configs.pop(scope_id, None), None)

    async def list_known_chat_ids(self, offset: int, limit: int) -> list[int]:
        ids = self.known | {key for key in self.configs if key > 0}
        ids |= {chat_id for chat_id, _, _ in self.usage}
        return sorted(ids)[offset : offset + limit]

    async def tokens_used_since(self, windows: dict[int, datetime]) -> dict[int, int]:
        totals: dict[int, int] = {}
        for chat_id, created_at, tokens in self.usage:
            if chat_id in windows and created_at >= windows[chat_id]:
                totals[chat_id] = totals.get(chat_id, 0) + tokens
        return totals

    async def list_audit(self, limit: int) -> list[QuotaAuditEntry]:
        return list(reversed(self.entries))[:limit]

    def _log(
        self,
        actor: int,
        subject: int,
        action: QuotaAction,
        before: QuotaConfig | None,
        after: QuotaConfig | None,
    ) -> None:
        self.entries.append(
            QuotaAuditEntry(
                id=len(self.entries) + 1,
                actor_chat_id=actor,
                subject_chat_id=subject,
                action=action,
                before=before,
                after=after,
                created_at=NOW,
            )
        )


@pytest.fixture
def repository() -> FakeQuotaRepository:
    return FakeQuotaRepository()


@pytest.fixture
def service(repository: FakeQuotaRepository) -> QuotaService:
    return QuotaService(repository, DEFAULTS, clock=lambda: NOW)


class TestQuotaConfig:
    @pytest.mark.parametrize(
        "payload",
        [
            {"token_limit": 0, "soft_ratio": 0.5, "window_minutes": 1},
            {"token_limit": 1_000_000_001, "soft_ratio": 0.5, "window_minutes": 1},
            {"token_limit": 1, "soft_ratio": 0, "window_minutes": 1},
            {"token_limit": 1, "soft_ratio": 1.01, "window_minutes": 1},
            {"token_limit": 1, "soft_ratio": 0.5, "window_minutes": 0},
            {"token_limit": 1, "soft_ratio": 0.5, "window_minutes": 525_601},
            {"token_limit": "10", "soft_ratio": 0.5, "window_minutes": 1},
            {"token_limit": 1, "soft_ratio": 0.5},
            {"token_limit": 1, "soft_ratio": 0.5, "window_minutes": 1, "extra": 1},
        ],
    )
    def test_rejects_out_of_bounds(self, payload: dict[str, object]) -> None:
        with pytest.raises(ValidationError):
            QuotaConfig.model_validate(payload)

    def test_accepts_upper_bounds(self) -> None:
        config = QuotaConfig(token_limit=1_000_000_000, soft_ratio=1, window_minutes=525_600)
        assert config.to_limits().soft_tokens == 1_000_000_000

    def test_limits_match_environment_arithmetic(self) -> None:
        usage = UsageSettings(_env_file=None, token_limit=1001, soft_ratio=0.33, window_minutes=7)
        config = QuotaConfig(token_limit=1001, soft_ratio=0.33, window_minutes=7)
        assert config.to_limits() == usage.to_limits()

    def test_settings_view_serializes_global_key(self) -> None:
        view = QuotaSettingsView(global_config=None, defaults=DEFAULTS, effective=DEFAULTS)
        assert set(view.model_dump()) == {"global", "defaults", "effective"}

    @pytest.mark.parametrize(
        ("global_config", "user_config", "expected"),
        [
            (None, None, (DEFAULTS, QuotaSource.ENVIRONMENT)),
            (GLOBAL, None, (GLOBAL, QuotaSource.GLOBAL)),
            (GLOBAL, USER, (USER, QuotaSource.USER)),
            (None, USER, (USER, QuotaSource.USER)),
        ],
    )
    def test_precedence_user_global_environment(
        self,
        global_config: QuotaConfig | None,
        user_config: QuotaConfig | None,
        expected: tuple[QuotaConfig, QuotaSource],
    ) -> None:
        assert resolve_quota(DEFAULTS, global_config, user_config) == expected


class TestResolve:
    @pytest.mark.asyncio
    async def test_changes_apply_on_next_call_without_caching(self, service: QuotaService) -> None:
        assert await service.resolve(7) == DEFAULTS.to_limits()
        await service.set_global(1, GLOBAL)
        assert await service.resolve(7) == GLOBAL.to_limits()
        await service.set_user(1, 7, USER)
        assert await service.resolve(7) == USER.to_limits()
        assert await service.resolve(8) == GLOBAL.to_limits()
        await service.clear_user(1, 7)
        assert await service.resolve(7) == GLOBAL.to_limits()
        await service.clear_global(1)
        assert await service.resolve(7) == DEFAULTS.to_limits()

    @pytest.mark.asyncio
    async def test_resolved_limits_window_and_thresholds(self, service: QuotaService) -> None:
        await service.set_user(1, 7, GLOBAL)
        limits = await service.resolve(7)
        assert (limits.hard_tokens, limits.soft_tokens, limits.window) == (
            1_000,
            500,
            timedelta(minutes=60),
        )


class TestAdministration:
    @pytest.mark.asyncio
    async def test_settings_global_defaults_effective(self, service: QuotaService) -> None:
        view = await service.settings()
        assert (view.global_config, view.defaults, view.effective) == (None, DEFAULTS, DEFAULTS)
        view = await service.set_global(1, GLOBAL)
        assert (view.global_config, view.effective) == (GLOBAL, GLOBAL)
        view = await service.clear_global(1)
        assert (view.global_config, view.effective) == (None, DEFAULTS)

    @pytest.mark.asyncio
    async def test_status_uses_each_users_own_rolling_window(
        self, service: QuotaService, repository: FakeQuotaRepository
    ) -> None:
        await service.set_global(1, GLOBAL)
        await service.set_user(1, 20, USER)
        repository.usage = [
            (10, NOW - timedelta(minutes=60), 100),  # exactly at window start: counted
            (10, NOW - timedelta(minutes=60, seconds=1), 1_000),
            (10, NOW - timedelta(minutes=30), 7),
            (20, NOW - timedelta(minutes=10), 5),
            (20, NOW - timedelta(minutes=11), 50),
        ]
        first = await service.user_status(10)
        assert (first.used_tokens, first.source, first.override, first.window_minutes) == (
            107,
            QuotaSource.GLOBAL,
            None,
            60,
        )
        second = await service.user_status(20)
        assert (second.used_tokens, second.hard_tokens, second.soft_tokens) == (5, 500, 500)
        assert (second.source, second.override) == (QuotaSource.USER, USER)

    @pytest.mark.asyncio
    async def test_unknown_user_reports_zero_consumption(self, service: QuotaService) -> None:
        status = await service.user_status(999)
        assert (status.used_tokens, status.source, status.hard_tokens) == (
            0,
            QuotaSource.ENVIRONMENT,
            150_000,
        )

    @pytest.mark.asyncio
    async def test_list_users_paginates(
        self, service: QuotaService, repository: FakeQuotaRepository
    ) -> None:
        repository.known = {3, 1, 2}
        await service.set_global(9, GLOBAL)
        page = await service.list_users(0, 2)
        assert ([user.chat_id for user in page.users], page.has_more) == ([1, 2], True)
        page = await service.list_users(2, 2)
        assert ([user.chat_id for user in page.users], page.has_more) == ([3], False)
        assert (await service.list_users(5, 2)).users == []

    @pytest.mark.asyncio
    async def test_override_removal_keeps_consumption(
        self, service: QuotaService, repository: FakeQuotaRepository
    ) -> None:
        repository.usage = [(5, NOW, 40)]
        status = await service.set_user(1, 5, USER)
        assert status.source == QuotaSource.USER
        status = await service.clear_user(1, 5)
        assert (status.source, status.override, status.used_tokens) == (
            QuotaSource.ENVIRONMENT,
            None,
            40,
        )

    @pytest.mark.asyncio
    async def test_audit_records_actor_subject_and_configs(
        self, service: QuotaService, repository: FakeQuotaRepository
    ) -> None:
        await service.set_global(1, GLOBAL)
        await service.set_user(2, 5, USER)
        await service.clear_user(2, 5)
        entries = await service.audit(500)
        assert [(e.actor_chat_id, e.subject_chat_id, e.action) for e in entries] == [
            (2, 5, QuotaAction.CLEAR_USER),
            (2, 5, QuotaAction.SET_USER),
            (1, GLOBAL_SCOPE_ID, QuotaAction.SET_GLOBAL),
        ]
        assert (entries[0].before, entries[0].after) == (USER, None)
        assert (entries[2].before, entries[2].after) == (None, GLOBAL)
