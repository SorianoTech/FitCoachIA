"""add trainer plan trace

Revision ID: f3a8c1d4e6b2
Revises: e7b2c4d9f1a3
Create Date: 2026-10-01 23:57:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a8c1d4e6b2"
down_revision: str | Sequence[str] | None = "e7b2c4d9f1a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store reproducibility metadata for newly generated training plans."""
    op.add_column("training_plans", sa.Column("model", sa.String(length=64), nullable=True))
    op.add_column("training_plans", sa.Column("skill_name", sa.String(length=64), nullable=True))
    op.add_column("training_plans", sa.Column("prompt_hash", sa.String(length=64), nullable=True))
    op.add_column("training_plans", sa.Column("skill_hash", sa.String(length=64), nullable=True))
    op.add_column("training_plans", sa.Column("retrieved_exercise_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove trainer reproducibility metadata."""
    op.drop_column("training_plans", "retrieved_exercise_ids")
    op.drop_column("training_plans", "skill_hash")
    op.drop_column("training_plans", "prompt_hash")
    op.drop_column("training_plans", "skill_name")
    op.drop_column("training_plans", "model")
