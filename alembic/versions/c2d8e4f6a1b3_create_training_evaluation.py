"""Add training_plans.goal, the job_execution table and the training_evaluation poll results."""

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
        "job_execution",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("dedup_key", sa.String(128), nullable=False, unique=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("execution_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "state IN ('pending', 'running', 'done', 'failed', 'cancelled')",
            name="ck_job_execution_state",
        ),
    )
    op.create_index(
        "ix_job_execution_due",
        "job_execution",
        ["execution_date"],
        postgresql_where=sa.text("state IN ('pending', 'running')"),
    )
    op.create_index("ix_job_execution_chat_id", "job_execution", ["chat_id"])
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
        sa.Column("job_id", sa.Uuid(), sa.ForeignKey("job_execution.id", ondelete="SET NULL")),
        sa.Column("answer_status", sa.String(16), nullable=False, server_default="awaiting"),
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
        sa.CheckConstraint(
            "answer_status IN ('awaiting', 'answered', 'unanswered')",
            name="ck_training_evaluation_answer_status",
        ),
    )
    op.create_index(
        "ix_training_evaluation_chat_id_sent_at", "training_evaluation", ["chat_id", "sent_at"]
    )


def downgrade() -> None:
    op.drop_table("training_evaluation")
    op.drop_table("job_execution")
    op.drop_column("training_plans", "goal")
