"""Mini App admin panel API. Admins come only from ``MINIAPP_ADMIN_CHAT_IDS`` in the env."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.api.miniapp_auth import get_miniapp_chat_id
from fitcoach.domain.quota import (
    MAX_AUDIT_ENTRIES,
    MAX_CHAT_ID,
    MAX_PAGE_SIZE,
    QuotaAuditEntry,
    QuotaConfig,
    QuotaSettingsView,
    UserQuotaPage,
    UserQuotaStatus,
)
from fitcoach.infrastructure.config.settings import (
    Settings,
    UsageSettings,
    get_settings,
    get_usage_settings,
)
from fitcoach.infrastructure.database.postgres_quota_repository import PostgresQuotaRepository
from fitcoach.infrastructure.database.session import get_session
from fitcoach.service.quota_service import QuotaService

logger = logging.getLogger(__name__)


def _is_admin(chat_id: int, settings: Settings) -> bool:
    return chat_id in settings.miniapp_admin_chat_ids


def require_admin(
    chat_id: Annotated[int, Depends(get_miniapp_chat_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> int:
    if not _is_admin(chat_id, settings):
        logger.warning("Mini App admin access denied")
        raise HTTPException(status_code=403, detail="No tienes permisos de administración.")
    return chat_id


def defaults_from(usage_settings: UsageSettings) -> QuotaConfig:
    # model_construct: the env fallback must keep working even beyond the panel's input bounds.
    return QuotaConfig.model_construct(
        token_limit=usage_settings.token_limit,
        soft_ratio=usage_settings.soft_ratio,
        window_minutes=usage_settings.window_minutes,
    )


async def get_quota_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    usage_settings: Annotated[UsageSettings, Depends(get_usage_settings)],
) -> QuotaService:
    return QuotaService(PostgresQuotaRepository(session), defaults_from(usage_settings))


class AdminAccess(BaseModel):
    is_admin: bool


admin_access = APIRouter(prefix="/api/miniapp/admin", tags=["miniapp-admin"])
admin = APIRouter(
    prefix="/api/miniapp/admin", tags=["miniapp-admin"], dependencies=[Depends(require_admin)]
)

Admin = Annotated[int, Depends(require_admin)]
Service = Annotated[QuotaService, Depends(get_quota_service)]
UserId = Annotated[int, Path(ge=1, le=MAX_CHAT_ID)]


@admin_access.get("/access", response_model=AdminAccess)
async def access(
    chat_id: Annotated[int, Depends(get_miniapp_chat_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AdminAccess:
    return AdminAccess(is_admin=_is_admin(chat_id, settings))


@admin.get("/settings", response_model=QuotaSettingsView)
async def read_settings(service: Service) -> QuotaSettingsView:
    return await service.settings()


@admin.put("/settings", response_model=QuotaSettingsView)
async def save_settings(config: QuotaConfig, actor: Admin, service: Service) -> QuotaSettingsView:
    logger.info("Quota global override saved by admin %s", actor)
    return await service.set_global(actor, config)


@admin.delete("/settings", response_model=QuotaSettingsView)
async def clear_settings(actor: Admin, service: Service) -> QuotaSettingsView:
    logger.info("Quota global override removed by admin %s", actor)
    return await service.clear_global(actor)


@admin.get("/users", response_model=UserQuotaPage)
async def list_users(
    service: Service,
    offset: Annotated[int, Query(ge=0, le=MAX_CHAT_ID)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25,
) -> UserQuotaPage:
    return await service.list_users(offset, limit)


@admin.get("/users/{chat_id}", response_model=UserQuotaStatus)
async def user_status(chat_id: UserId, service: Service) -> UserQuotaStatus:
    return await service.user_status(chat_id)


@admin.put("/users/{chat_id}", response_model=UserQuotaStatus)
async def save_user(
    chat_id: UserId, config: QuotaConfig, actor: Admin, service: Service
) -> UserQuotaStatus:
    logger.info("Quota override for chat %s saved by admin %s", chat_id, actor)
    return await service.set_user(actor, chat_id, config)


@admin.delete("/users/{chat_id}", response_model=UserQuotaStatus)
async def clear_user(chat_id: UserId, actor: Admin, service: Service) -> UserQuotaStatus:
    logger.info("Quota override for chat %s removed by admin %s", chat_id, actor)
    return await service.clear_user(actor, chat_id)


@admin.get("/audit", response_model=list[QuotaAuditEntry])
async def audit(
    service: Service,
    limit: Annotated[int, Query(ge=1, le=MAX_AUDIT_ENTRIES)] = MAX_AUDIT_ENTRIES,
) -> list[QuotaAuditEntry]:
    return await service.audit(limit)
