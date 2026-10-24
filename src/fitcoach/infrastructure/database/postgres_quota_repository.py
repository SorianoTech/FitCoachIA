from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, or_, select, union
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.domain.quota import QuotaAction, QuotaAuditEntry, QuotaConfig
from fitcoach.infrastructure.database.models import (
    InterviewSessionRecord,
    QuotaAuditRecord,
    QuotaConfigRecord,
    TokenUsageRecord,
    TrainingSessionRecord,
)


def _to_config(record: QuotaConfigRecord) -> QuotaConfig:
    return QuotaConfig(
        token_limit=record.token_limit,
        soft_ratio=record.soft_ratio,
        window_minutes=record.window_minutes,
    )


def _dump(config: QuotaConfig | None) -> dict[str, object] | None:
    return None if config is None else config.model_dump(mode="json")


class PostgresQuotaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_configs(self, chat_ids: list[int]) -> dict[int, QuotaConfig]:
        records = await self._session.scalars(
            select(QuotaConfigRecord)
            .where(QuotaConfigRecord.scope_id.in_(set(chat_ids)))
            .execution_options(populate_existing=True)
        )
        return {record.scope_id: _to_config(record) for record in records}

    async def save_config(
        self, actor_chat_id: int, scope_id: int, config: QuotaConfig, action: QuotaAction
    ) -> None:
        try:
            before = await self._locked(scope_id)
            values = config.model_dump()
            statement = insert(QuotaConfigRecord).values(
                scope_id=scope_id, updated_by=actor_chat_id, **values
            )
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[QuotaConfigRecord.scope_id],
                    set_={**values, "updated_by": actor_chat_id, "updated_at": func.now()},
                )
            )
            self._audit(actor_chat_id, scope_id, action, before, config)
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise

    async def delete_config(self, actor_chat_id: int, scope_id: int, action: QuotaAction) -> None:
        try:
            before = await self._locked(scope_id)
            await self._session.execute(
                delete(QuotaConfigRecord).where(QuotaConfigRecord.scope_id == scope_id)
            )
            self._audit(actor_chat_id, scope_id, action, before, None)
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise

    async def list_known_chat_ids(self, offset: int, limit: int) -> list[int]:
        known = union(
            select(InterviewSessionRecord.chat_id.label("chat_id")),
            select(TrainingSessionRecord.chat_id.label("chat_id")),
            select(TokenUsageRecord.chat_id.label("chat_id")),
            select(QuotaConfigRecord.scope_id.label("chat_id")),
        ).subquery()
        rows = await self._session.scalars(
            select(known.c.chat_id)
            .where(known.c.chat_id > 0)
            .order_by(known.c.chat_id)
            .offset(offset)
            .limit(limit)
        )
        return list(rows)

    async def tokens_used_since(self, windows: dict[int, datetime]) -> dict[int, int]:
        if not windows:
            return {}
        rows = await self._session.execute(
            select(TokenUsageRecord.chat_id, func.sum(TokenUsageRecord.total_tokens))
            .where(
                or_(
                    *(
                        and_(
                            TokenUsageRecord.chat_id == chat_id,
                            TokenUsageRecord.created_at >= since,
                        )
                        for chat_id, since in windows.items()
                    )
                )
            )
            .group_by(TokenUsageRecord.chat_id)
        )
        return {int(chat_id): int(total or 0) for chat_id, total in rows}

    async def list_audit(self, limit: int) -> list[QuotaAuditEntry]:
        records = await self._session.scalars(
            select(QuotaAuditRecord).order_by(QuotaAuditRecord.id.desc()).limit(limit)
        )
        return [
            QuotaAuditEntry(
                id=record.id,
                actor_chat_id=record.actor_chat_id,
                subject_chat_id=record.subject_chat_id,
                action=QuotaAction(record.action),
                before=None if record.before is None else QuotaConfig.model_validate(record.before),
                after=None if record.after is None else QuotaConfig.model_validate(record.after),
                created_at=record.created_at.astimezone(UTC),
            )
            for record in records
        ]

    async def _locked(self, scope_id: int) -> QuotaConfig | None:
        record = await self._session.scalar(
            select(QuotaConfigRecord)
            .where(QuotaConfigRecord.scope_id == scope_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return None if record is None else _to_config(record)

    def _audit(
        self,
        actor_chat_id: int,
        scope_id: int,
        action: QuotaAction,
        before: QuotaConfig | None,
        after: QuotaConfig | None,
    ) -> None:
        self._session.add(
            QuotaAuditRecord(
                actor_chat_id=actor_chat_id,
                subject_chat_id=scope_id,
                action=action.value,
                before=_dump(before),
                after=_dump(after),
                created_at=datetime.now(UTC),
            )
        )
