from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.infrastructure.database.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from fitcoach.infrastructure.database.session import get_session


async def get_conversation_repository(
    session: AsyncSession = Depends(get_session),
) -> PostgresConversationRepository:
    return PostgresConversationRepository(session)
