"""add interview profiles

Revision ID: 6ca1174fc623
Revises: c5ae33575d94
Create Date: 2026-09-06 20:07:21.411493

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6ca1174fc623"
down_revision: str | None = "c5ae33575d94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "interview_sessions",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("chat_id"),
    )
    op.create_table(
        "interviewer_profiles",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("profile", sa.JSON(), nullable=False),
        sa.Column("report", sa.Text(), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("chat_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("interviewer_profiles")
    op.drop_table("interview_sessions")
