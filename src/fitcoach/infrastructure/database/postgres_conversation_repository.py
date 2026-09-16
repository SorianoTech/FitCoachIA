from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.domain.conversation import ConversationMessage
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.infrastructure.database.models import (
    ConversationMessageRecord,
    InterviewerProfileRecord,
    InterviewSessionRecord,
    ModelPriceRecord,
    TokenUsageRecord,
)


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
    ) -> int:
        assistant_message = ConversationMessageRecord(
            chat_id=chat_id,
            role="assistant",
            content=assistant_content,
        )
        self._session.add_all([
            ConversationMessageRecord(chat_id=chat_id, role="user", content=user_content),
            assistant_message,
        ])
        await self._session.commit()
        return assistant_message.id

    async def get_interview_status(self, chat_id: int) -> str | None:
        status = await self._session.scalar(
            select(InterviewSessionRecord.status).where(InterviewSessionRecord.chat_id == chat_id)
        )
        return status if isinstance(status, str) else None

    async def restart_interview(self, chat_id: int) -> None:
        await self._session.execute(
            delete(ConversationMessageRecord).where(ConversationMessageRecord.chat_id == chat_id)
        )
        await self._session.execute(
            delete(InterviewerProfileRecord).where(InterviewerProfileRecord.chat_id == chat_id)
        )
        await self._session.execute(
            delete(InterviewSessionRecord).where(InterviewSessionRecord.chat_id == chat_id)
        )
        self._session.add(InterviewSessionRecord(chat_id=chat_id, status="in_progress"))
        await self._session.commit()

    async def complete_interview(
        self,
        chat_id: int,
        user_content: str,
        assistant_content: str,
        profile: InterviewerProfile,
        report: str,
    ) -> int:
        assistant_message = ConversationMessageRecord(
            chat_id=chat_id, role="assistant", content=assistant_content
        )
        self._session.add_all([
            ConversationMessageRecord(chat_id=chat_id, role="user", content=user_content),
            assistant_message,
            InterviewerProfileRecord(
                chat_id=chat_id,
                profile=profile.model_dump(mode="json"),
                report=report,
            ),
        ])
        session = await self._session.get(InterviewSessionRecord, chat_id)
        if session is None:
            session = InterviewSessionRecord(chat_id=chat_id, status="completed")
            self._session.add(session)
        else:
            session.status = "completed"
        session.completed_at = func.now()
        await self._session.commit()
        return assistant_message.id

    async def record_token_usage(
        self,
        chat_id: int,
        agent: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        latency_ms: int,
        status: str,
        conversation_message_id: int | None,
    ) -> None:
        price = await self._session.get(ModelPriceRecord, model)
        cost_usd = None
        if price is not None:
            cost_usd = (
                (
                    Decimal(prompt_tokens) * Decimal(str(price.input_usd_per_million))
                    + Decimal(completion_tokens) * Decimal(str(price.output_usd_per_million))
                )
                / Decimal(1_000_000)
            ).quantize(Decimal("0.000001"))
        self._session.add(
            TokenUsageRecord(
                chat_id=chat_id,
                agent=agent,
                model=model,
                conversation_message_id=conversation_message_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                status=status,
                cost_usd=cost_usd,
            )
        )
        await self._session.commit()
