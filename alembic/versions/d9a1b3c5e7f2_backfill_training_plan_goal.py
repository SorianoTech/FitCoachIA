"""Backfill training_plans.goal from the stored plan JSON."""

from collections.abc import Sequence

from alembic import op

revision: str = "d9a1b3c5e7f2"
down_revision: str | Sequence[str] | None = "c2d8e4f6a1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE training_plans SET goal = plan->>'goal' WHERE goal IS NULL")


def downgrade() -> None:
    # The schema revision drops the column; nothing to undo here.
    pass
