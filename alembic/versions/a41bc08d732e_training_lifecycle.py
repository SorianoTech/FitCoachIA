"""Persist mesocycles, confirmation workflows and reminder events."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a41bc08d732e"
down_revision: str | Sequence[str] | None = "f3a8c1d4e6b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "training_mesocycles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "previous_cycle_id",
            sa.Integer(),
            sa.ForeignKey("training_mesocycles.id", ondelete="SET NULL"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("expected_end_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("reminders_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("message_thread_id", sa.BigInteger()),
    )
    op.create_index("ix_training_mesocycles_chat_id", "training_mesocycles", ["chat_id"])
    op.create_index(
        "ix_training_mesocycles_expected_end_at", "training_mesocycles", ["expected_end_at"]
    )
    op.add_column(
        "training_plans",
        sa.Column(
            "mesocycle_id",
            sa.Integer(),
            sa.ForeignKey("training_mesocycles.id", ondelete="SET NULL"),
        ),
    )
    op.add_column(
        "training_plans",
        sa.Column(
            "parent_plan_id", sa.Integer(), sa.ForeignKey("training_plans.id", ondelete="SET NULL")
        ),
    )
    op.add_column(
        "training_plans",
        sa.Column("change_kind", sa.String(32), nullable=False, server_default="initial"),
    )
    # One legacy generation was one independent block. Dates remain unknown.
    op.execute("""
        INSERT INTO training_mesocycles (id, chat_id)
        SELECT id, chat_id FROM training_plans
    """)
    op.execute("UPDATE training_plans SET mesocycle_id = id")
    op.execute("""
        SELECT setval(pg_get_serial_sequence('training_mesocycles', 'id'),
                      COALESCE((SELECT MAX(id) FROM training_mesocycles), 1),
                      EXISTS(SELECT 1 FROM training_mesocycles))
    """)
    op.create_table(
        "training_workflows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "base_plan_id",
            sa.Integer(),
            sa.ForeignKey("training_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_training_workflows_chat_id", "training_workflows", ["chat_id"])
    op.create_index(
        "uq_training_workflows_open_chat",
        "training_workflows",
        ["chat_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('reviewing', 'generating', 'awaiting_confirmation')"),
    )
    op.create_table(
        "training_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "mesocycle_id",
            sa.Integer(),
            sa.ForeignKey("training_mesocycles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("occasion", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("mesocycle_id", "occasion", name="uq_training_notifications_occasion"),
    )


def downgrade() -> None:
    op.drop_table("training_notifications")
    op.drop_table("training_workflows")
    op.drop_column("training_plans", "change_kind")
    op.drop_column("training_plans", "parent_plan_id")
    op.drop_column("training_plans", "mesocycle_id")
    op.drop_table("training_mesocycles")
