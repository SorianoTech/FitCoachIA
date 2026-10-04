"""Resolves and administers LLM quotas. Reads the store on every call: no process caching."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fitcoach.domain.quota import (
    GLOBAL_SCOPE_ID,
    MAX_AUDIT_ENTRIES,
    QuotaAction,
    QuotaAuditEntry,
    QuotaConfig,
    QuotaRepository,
    QuotaSettingsView,
    UserQuotaPage,
    UserQuotaStatus,
    resolve_quota,
)
from fitcoach.domain.rate_limiter import UsageLimits


class QuotaService:
    def __init__(
        self,
        repository: QuotaRepository,
        defaults: QuotaConfig,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._defaults = defaults
        self._clock = clock

    async def resolve(self, chat_id: int) -> UsageLimits:
        configs = await self._repository.get_configs([GLOBAL_SCOPE_ID, chat_id])
        config, _ = resolve_quota(
            self._defaults, configs.get(GLOBAL_SCOPE_ID), configs.get(chat_id)
        )
        return config.to_limits()

    async def settings(self) -> QuotaSettingsView:
        configs = await self._repository.get_configs([GLOBAL_SCOPE_ID])
        global_config = configs.get(GLOBAL_SCOPE_ID)
        effective, _ = resolve_quota(self._defaults, global_config, None)
        return QuotaSettingsView(
            global_config=global_config, defaults=self._defaults, effective=effective
        )

    async def set_global(self, actor_chat_id: int, config: QuotaConfig) -> QuotaSettingsView:
        await self._repository.save_config(
            actor_chat_id, GLOBAL_SCOPE_ID, config, QuotaAction.SET_GLOBAL
        )
        return await self.settings()

    async def clear_global(self, actor_chat_id: int) -> QuotaSettingsView:
        await self._repository.delete_config(
            actor_chat_id, GLOBAL_SCOPE_ID, QuotaAction.CLEAR_GLOBAL
        )
        return await self.settings()

    async def list_users(self, offset: int, limit: int) -> UserQuotaPage:
        chat_ids = await self._repository.list_known_chat_ids(offset, limit + 1)
        page = chat_ids[:limit]
        users = await self._statuses(page)
        return UserQuotaPage(
            users=users, offset=offset, limit=limit, has_more=len(chat_ids) > limit
        )

    async def user_status(self, chat_id: int) -> UserQuotaStatus:
        return (await self._statuses([chat_id]))[0]

    async def set_user(
        self, actor_chat_id: int, chat_id: int, config: QuotaConfig
    ) -> UserQuotaStatus:
        await self._repository.save_config(actor_chat_id, chat_id, config, QuotaAction.SET_USER)
        return await self.user_status(chat_id)

    async def clear_user(self, actor_chat_id: int, chat_id: int) -> UserQuotaStatus:
        await self._repository.delete_config(actor_chat_id, chat_id, QuotaAction.CLEAR_USER)
        return await self.user_status(chat_id)

    async def audit(self, limit: int = MAX_AUDIT_ENTRIES) -> list[QuotaAuditEntry]:
        return await self._repository.list_audit(min(limit, MAX_AUDIT_ENTRIES))

    async def _statuses(self, chat_ids: list[int]) -> list[UserQuotaStatus]:
        if not chat_ids:
            return []
        configs = await self._repository.get_configs([GLOBAL_SCOPE_ID, *chat_ids])
        global_config = configs.get(GLOBAL_SCOPE_ID)
        now = self._clock()
        resolved = {
            chat_id: resolve_quota(self._defaults, global_config, configs.get(chat_id))
            for chat_id in chat_ids
        }
        used = await self._repository.tokens_used_since({
            chat_id: now - timedelta(minutes=config.window_minutes)
            for chat_id, (config, _) in resolved.items()
        })
        statuses = []
        for chat_id in chat_ids:
            config, source = resolved[chat_id]
            limits = config.to_limits()
            statuses.append(
                UserQuotaStatus(
                    chat_id=chat_id,
                    used_tokens=used.get(chat_id, 0),
                    hard_tokens=limits.hard_tokens,
                    soft_tokens=limits.soft_tokens,
                    window_minutes=config.window_minutes,
                    source=source,
                    override=configs.get(chat_id),
                )
            )
        return statuses
