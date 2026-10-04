"""Add training_plans.goal and the training_evaluation poll table."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c2d8e4f6a1b3"
down_revision: str | Sequence[str] | None = "a41bc08d732e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("training_plans", sa.Column("goal", sa.String(32), nullable=True))
    op.create_table(
        "training_evaluation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "plan_id",
            sa.Integer(),
            sa.ForeignKey("training_plans.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "mesocycle_id",
            sa.Integer(),
            sa.ForeignKey("training_mesocycles.id", ondelete="SET NULL"),
        ),
        sa.Column("goal", sa.String(32)),
        sa.Column("week_number", sa.SmallInteger(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("telegram_poll_id", sa.String(64), unique=True),
        sa.Column("telegram_message_id", sa.BigInteger()),
        sa.Column("score", sa.SmallInteger()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "mesocycle_id", "week_number", name="uq_training_evaluation_cycle_week"
        ),
        sa.CheckConstraint("week_number BETWEEN 1 AND 4", name="ck_training_evaluation_week"),
        sa.CheckConstraint("score BETWEEN 0 AND 5", name="ck_training_evaluation_score"),
    )
    op.create_index(
        "ix_training_evaluation_due",
        "training_evaluation",
        ["due_at"],
        postgresql_where=sa.text("state IN ('pending', 'sending')"),
    )
    op.create_index(
        "ix_training_evaluation_chat_id_sent_at", "training_evaluation", ["chat_id", "sent_at"]
    )


def downgrade() -> None:
    op.drop_table("training_evaluation")
    op.drop_column("training_plans", "goal")
