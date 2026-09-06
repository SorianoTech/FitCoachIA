from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.domain.conversation import ConversationMessage
from fitcoach.infrastructure.database.models import ConversationMessageRecord


class PostgresConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_recent(self, chat_id: int, limit: int) -> list[ConversationMessage]:
        statement = (
            select(ConversationMessageRecord)
            .where(ConversationMessageRecord.chat_id == chat_id)
            .order_by(ConversationMessageRecord.id.desc())
            .limit(limit)
        )
        records = list((await self._session.scalars(statement)).all())
        return [
            ConversationMessage(
                chat_id=record.chat_id,
                role=record.role,
                content=record.content,
                created_at=record.created_at,
            )
            for record in reversed(records)
        ]

    async def add_turn(
        self,
        chat_id: int,
        user_content: str,
        assistant_content: str,
    ) -> None:
        self._session.add_all([
            ConversationMessageRecord(chat_id=chat_id, role="user", content=user_content),
            ConversationMessageRecord(
                chat_id=chat_id,
                role="assistant",
                content=assistant_content,
            ),
        ])
        await self._session.commit()
