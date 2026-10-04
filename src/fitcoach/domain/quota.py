"""Configurable LLM quotas: per-user override > panel global > environment fallback."""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Final, Protocol

from pydantic import BaseModel, ConfigDict, Field

from fitcoach.domain.rate_limiter import UsageLimits

GLOBAL_SCOPE_ID: Final = 0
MAX_CHAT_ID: Final = 2**63 - 1
MAX_TOKEN_LIMIT: Final = 1_000_000_000
MAX_WINDOW_MINUTES: Final = 525_600
MAX_PAGE_SIZE: Final = 100
MAX_AUDIT_ENTRIES: Final = 100


class QuotaConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    token_limit: Annotated[int, Field(gt=0, le=MAX_TOKEN_LIMIT, strict=True)]
    soft_ratio: Annotated[float, Field(gt=0, le=1)]
    window_minutes: Annotated[int, Field(gt=0, le=MAX_WINDOW_MINUTES, strict=True)]

    def to_limits(self) -> UsageLimits:
        # Same arithmetic as UsageSettings.to_limits so the env fallback is unchanged.
        return UsageLimits(
            hard_tokens=self.token_limit,
            soft_tokens=int(self.token_limit * self.soft_ratio),
            window=timedelta(minutes=self.window_minutes),
        )


class QuotaSource(StrEnum):
    USER = "user"
    GLOBAL = "global"
    ENVIRONMENT = "environment"


class QuotaAction(StrEnum):
    SET_GLOBAL = "set_global"
    CLEAR_GLOBAL = "clear_global"
    SET_USER = "set_user"
    CLEAR_USER = "clear_user"


def resolve_quota(
    defaults: QuotaConfig, global_config: QuotaConfig | None, user_config: QuotaConfig | None
) -> tuple[QuotaConfig, QuotaSource]:
    if user_config is not None:
        return user_config, QuotaSource.USER
    if global_config is not None:
        return global_config, QuotaSource.GLOBAL
    return defaults, QuotaSource.ENVIRONMENT


class QuotaSettingsView(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    global_config: QuotaConfig | None = Field(alias="global")
    defaults: QuotaConfig
    effective: QuotaConfig


class UserQuotaStatus(BaseModel):
    chat_id: int
    used_tokens: int
    hard_tokens: int
    soft_tokens: int
    window_minutes: int
    source: QuotaSource
    override: QuotaConfig | None


class UserQuotaPage(BaseModel):
    users: list[UserQuotaStatus]
    offset: int
    limit: int
    has_more: bool


class QuotaAuditEntry(BaseModel):
    id: int
    actor_chat_id: int
    subject_chat_id: int
    action: QuotaAction
    before: QuotaConfig | None
    after: QuotaConfig | None
    created_at: datetime


class QuotaRepository(Protocol):
    async def get_configs(self, chat_ids: list[int]) -> dict[int, QuotaConfig]:
        """Configured rows for the given scope ids (``GLOBAL_SCOPE_ID`` is the global row)."""
        ...

    async def save_config(
        self, actor_chat_id: int, scope_id: int, config: QuotaConfig, action: QuotaAction
    ) -> None:
        """Upsert the row and append the audit entry atomically."""
        ...

    async def delete_config(self, actor_chat_id: int, scope_id: int, action: QuotaAction) -> None:
        """Remove the row (if any) and append the audit entry atomically."""
        ...

    async def list_known_chat_ids(self, offset: int, limit: int) -> list[int]: ...

    async def tokens_used_since(self, windows: dict[int, datetime]) -> dict[int, int]:
        """Tokens consumed per chat since its own window start."""
        ...

    async def list_audit(self, limit: int) -> list[QuotaAuditEntry]: ...
