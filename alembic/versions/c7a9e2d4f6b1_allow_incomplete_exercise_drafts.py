"""Allow an exercise draft to wait for user clarification."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7a9e2d4f6b1"
down_revision: str | Sequence[str] | None = "b6e4f2a1c9d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("exercise_submissions", "proposal", existing_type=sa.JSON(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM exercise_submissions WHERE proposal IS NULL")
    op.alter_column("exercise_submissions", "proposal", existing_type=sa.JSON(), nullable=False)
