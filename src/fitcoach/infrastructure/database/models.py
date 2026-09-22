from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from fitcoach.domain.agents import AgentType
from fitcoach.domain.conversation import MessageRole


class Base(DeclarativeBase):
    pass


class ConversationMessageRecord(Base):
    """One user/assistant message. ``agent`` keeps each agent's history apart.

    Without it the Trainer's follow-up Q&A would inherit the whole interview
    transcript, since history is otherwise keyed on ``chat_id`` alone.
    """

    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("ix_conversation_messages_chat_id_id", "chat_id", "id"),
        Index("ix_conversation_messages_chat_id_agent_id", "chat_id", "agent", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    agent: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=AgentType.INTERVIEWER.value
    )
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


class TrainingPlanRecord(Base):
    """One generated mesocycle. Plans are versioned, never overwritten.

    A repeated ``/train`` appends version N+1 so the history stays available to
    the Nutritionist agent, which needs the training volume it was built on.
    """

    __tablename__ = "training_plans"
    __table_args__ = (
        UniqueConstraint("chat_id", "version", name="uq_training_plans_chat_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    plan: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    report: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TrainingSessionRecord(Base):
    __tablename__ = "training_sessions"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    current_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_plans.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ModelPriceRecord(Base):
    __tablename__ = "model_prices"

    model: Mapped[str] = mapped_column(String(64), primary_key=True)
    input_usd_per_million: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    output_usd_per_million: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)


class TokenUsageRecord(Base):
    """One row per LLM call (see docs/plan/observabilidad.md for the schema rationale).

    ``chat_id`` doubles as the Telegram user id: today every chat is a private
    1:1 chat, same assumption ``conversation_messages``/``interview_sessions``
    already make. Revisit if group/forum chats are ever supported.
    """

    __tablename__ = "token_usage"
    __table_args__ = (
        Index("ix_token_usage_chat_id_created_at", "chat_id", "created_at"),
        Index("ix_token_usage_agent_created_at", "agent", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    agent: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    # Nullable: the JSON-repair retry call consumes tokens but never becomes a
    # persisted turn on its own.
    conversation_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="SET NULL"), nullable=True
    )
    prompt_tokens: Mapped[int] = mapped_column(nullable=False)
    completion_tokens: Mapped[int] = mapped_column(nullable=False)
    total_tokens: Mapped[int] = mapped_column(nullable=False)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    latency_ms: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
