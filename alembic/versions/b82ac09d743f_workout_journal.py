"""Add real workout journal without changing prescriptions."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b82ac09d743f"
down_revision: str | Sequence[str] | None = "a41bc08d732e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workout_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("training_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mesocycle_id",
            sa.Integer(),
            sa.ForeignKey("training_mesocycles.id", ondelete="CASCADE"),
        ),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("day", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="in_progress"),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("prescription", sa.JSON(), nullable=False),
        sa.Column("exercises", sa.JSON(), nullable=False),
        sa.UniqueConstraint("chat_id", "request_id", name="uq_workout_sessions_request"),
    )
    op.create_index("ix_workout_sessions_chat_id_id", "workout_sessions", ["chat_id", "id"])
    op.create_index(
        "uq_workout_sessions_cycle_slot",
        "workout_sessions",
        ["chat_id", "mesocycle_id", "week", "day"],
        unique=True,
        postgresql_where=sa.text("mesocycle_id IS NOT NULL"),
    )
    op.create_index(
        "uq_workout_sessions_legacy_slot",
        "workout_sessions",
        ["chat_id", "plan_id", "week", "day"],
        unique=True,
        postgresql_where=sa.text("mesocycle_id IS NULL"),
    )
    op.create_table(
        "workout_requests",
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("workout_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("training_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("workout_requests")
    op.drop_table("workout_sessions")
