from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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
    """One confirmed plan version, never overwritten.

    The first generation and accepted proposals append versions. A renewal opens
    a mesocycle; an exercise swap keeps the existing mesocycle and its dates.
    Drafts live in training_workflows and do not receive a version until accepted.
    """

    __tablename__ = "training_plans"
    __table_args__ = (
        UniqueConstraint("chat_id", "version", name="uq_training_plans_chat_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    mesocycle_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_mesocycles.id", ondelete="SET NULL")
    )
    parent_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_plans.id", ondelete="SET NULL")
    )
    change_kind: Mapped[str] = mapped_column(String(32), server_default="initial")
    plan: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    report: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skill_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skill_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retrieved_exercise_ids: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
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


class TrainingMesocycleRecord(Base):
    __tablename__ = "training_mesocycles"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    previous_cycle_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_mesocycles.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminders_enabled: Mapped[bool] = mapped_column(default=True, server_default="true")
    message_thread_id: Mapped[int | None] = mapped_column(BigInteger)


class TrainingWorkflowRecord(Base):
    __tablename__ = "training_workflows"
    __table_args__ = (
        Index(
            "uq_training_workflows_open_chat",
            "chat_id",
            unique=True,
            postgresql_where=text("state IN ('reviewing', 'generating', 'awaiting_confirmation')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    base_plan_id: Mapped[int] = mapped_column(
        ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)


class TrainingNotificationRecord(Base):
    __tablename__ = "training_notifications"
    __table_args__ = (
        UniqueConstraint("mesocycle_id", "occasion", name="uq_training_notifications_occasion"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    mesocycle_id: Mapped[int] = mapped_column(
        ForeignKey("training_mesocycles.id", ondelete="CASCADE"), nullable=False
    )
    occasion: Mapped[int] = mapped_column(default=0, server_default="0")
    state: Mapped[str] = mapped_column(String(32), default="pending", server_default="pending")
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")


class ProcessedUpdateRecord(Base):
    """Telegram ``update_id`` already taken by a worker.

    Telegram re-delivers an update when the webhook does not answer in time, so
    a slow ``/train`` would otherwise be processed (and billed) once per retry.
    """

    __tablename__ = "processed_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExerciseSubmissionRecord(Base):
    __tablename__ = "exercise_submissions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'pending', 'approved', 'rejected', 'cancelled')",
            name="ck_exercise_submissions_status",
        ),
        Index("ix_exercise_submissions_status_id", "status", "id"),
        Index(
            "uq_exercise_submissions_draft_chat",
            "chat_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_thread_id: Mapped[int | None] = mapped_column(BigInteger)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    proposal: Mapped[dict[str, object] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    duplicate_exercise_id: Mapped[int | None] = mapped_column(BigInteger)
    moderation_notes: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    published_exercise_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class WorkoutSessionRecord(Base):
    __tablename__ = "workout_sessions"
    __table_args__ = (
        UniqueConstraint("chat_id", "request_id", name="uq_workout_sessions_request"),
        Index(
            "uq_workout_sessions_cycle_slot",
            "chat_id",
            "mesocycle_id",
            "week",
            "day",
            unique=True,
            postgresql_where=text("mesocycle_id IS NOT NULL"),
        ),
        Index(
            "uq_workout_sessions_legacy_slot",
            "chat_id",
            "plan_id",
            "week",
            "day",
            unique=True,
            postgresql_where=text("mesocycle_id IS NULL"),
        ),
        Index("ix_workout_sessions_chat_id_id", "chat_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False
    )
    mesocycle_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_mesocycles.id", ondelete="CASCADE")
    )
    week: Mapped[int] = mapped_column(nullable=False)
    day: Mapped[int] = mapped_column(nullable=False)
    revision: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="in_progress", server_default="in_progress"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prescription: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    exercises: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)


class WorkoutRequestRecord(Base):
    """Every start/resume UUID retains its original payload, including after swaps."""

    __tablename__ = "workout_requests"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("workout_sessions.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("training_plans.id", ondelete="CASCADE"), nullable=False
    )


class QuotaConfigRecord(Base):
    """Quota configured from the admin panel. ``scope_id`` 0 is the global row; others a chat."""

    __tablename__ = "quota_configs"
    __table_args__ = (
        CheckConstraint("scope_id >= 0", name="ck_quota_configs_scope_id"),
        CheckConstraint(
            "token_limit > 0 AND token_limit <= 1000000000", name="ck_quota_configs_token_limit"
        ),
        CheckConstraint("soft_ratio > 0 AND soft_ratio <= 1", name="ck_quota_configs_soft_ratio"),
        CheckConstraint(
            "window_minutes > 0 AND window_minutes <= 525600",
            name="ck_quota_configs_window_minutes",
        ),
    )

    scope_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    token_limit: Mapped[int] = mapped_column(nullable=False)
    soft_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    window_minutes: Mapped[int] = mapped_column(nullable=False)
    updated_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QuotaAuditRecord(Base):
    """Append-only history of quota changes. Stores ids and configs only, never user data."""

    __tablename__ = "quota_audit"
    __table_args__ = (Index("ix_quota_audit_subject_chat_id_id", "subject_chat_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
