"""Create the moderated exercise submission workflow."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b6e4f2a1c9d8"
down_revision: str | Sequence[str] | None = "c3d7e9f1a2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exercise_submissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_thread_id", sa.BigInteger(), nullable=True),
        sa.Column("raw_description", sa.Text(), nullable=False),
        sa.Column("proposal", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("duplicate_exercise_id", sa.BigInteger(), nullable=True),
        sa.Column("moderation_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("published_exercise_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'pending', 'approved', 'rejected', 'cancelled')",
            name="ck_exercise_submissions_status",
        ),
    )
    op.create_index(
        "ix_exercise_submissions_status_id", "exercise_submissions", ["status", "id"]
    )
    op.create_index(
        "uq_exercise_submissions_draft_chat",
        "exercise_submissions",
        ["chat_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )


def downgrade() -> None:
    op.drop_index("uq_exercise_submissions_draft_chat", table_name="exercise_submissions")
    op.drop_index("ix_exercise_submissions_status_id", table_name="exercise_submissions")
    op.drop_table("exercise_submissions")
