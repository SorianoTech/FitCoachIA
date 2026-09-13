from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Index, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from fitcoach.domain.conversation import MessageRole


class Base(DeclarativeBase):
    pass


class ConversationMessageRecord(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (Index("ix_conversation_messages_chat_id_id", "chat_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[MessageRole] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InterviewSessionRecord(Base):
    __tablename__ = "interview_sessions"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InterviewerProfileRecord(Base):
    __tablename__ = "interviewer_profiles"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    profile: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    report: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
