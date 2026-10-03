"""add trainer agent

Adds the Trainer's own tables and the ``agent`` discriminator that keeps each
agent's conversation history apart.

Revision ID: d4f1a9b7c3e2
Revises: ab12cd34ef56
Create Date: 2026-09-21 10:12:44.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4f1a9b7c3e2"
down_revision: str | Sequence[str] | None = "ab12cd34ef56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default backfills the rows written before the Trainer existed;
    # every one of them belongs to the interviewer.
    op.add_column(
        "conversation_messages",
        sa.Column(
            "agent",
            sa.String(length=32),
            nullable=False,
            server_default="interviewer",
        ),
    )
    op.create_index(
        "ix_conversation_messages_chat_id_agent_id",
        "conversation_messages",
        ["chat_id", "agent", "id"],
    )
    op.create_table(
        "training_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("report", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chat_id", "version", name="uq_training_plans_chat_version"),
    )
    op.create_table(
        "training_sessions",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_plan_id", sa.Integer(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["current_plan_id"], ["training_plans.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("chat_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("training_sessions")
    op.drop_table("training_plans")
    op.drop_index("ix_conversation_messages_chat_id_agent_id", table_name="conversation_messages")
    op.drop_column("conversation_messages", "agent")
