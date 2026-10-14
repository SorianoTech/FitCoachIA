"""Drop the legacy training_notifications queue, replaced by job_execution."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7d3f1c9e2b5"
down_revision: str | Sequence[str] | None = "f8b2d6a4c1e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("training_notifications")


def downgrade() -> None:
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
