"""Schedule the future weekly polls of the mesocycles already open."""

from collections.abc import Sequence

from alembic import op

revision: str = "e5c7a9b1d3f4"
down_revision: str | Sequence[str] | None = "d9a1b3c5e7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Future weeks only: past weeks are never asked retroactively.
    op.execute(
        """
        INSERT INTO training_evaluation (chat_id, mesocycle_id, week_number, due_at)
        SELECT c.chat_id, c.id, w.week, c.started_at + w.week * interval '7 days'
        FROM training_mesocycles c
        JOIN training_plans p ON p.mesocycle_id = c.id
        JOIN training_sessions s ON s.current_plan_id = p.id
        CROSS JOIN generate_series(1, 4) AS w(week)
        WHERE c.started_at IS NOT NULL
          AND c.completed_at IS NULL
          AND c.started_at + w.week * interval '7 days' > now()
        ON CONFLICT ON CONSTRAINT uq_training_evaluation_cycle_week DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM training_evaluation WHERE state = 'pending' AND sent_at IS NULL")
