"""Move the pending reminders and the future polls of the open cycles to job_execution."""

from collections.abc import Sequence

from alembic import op

revision: str = "e5c7a9b1d3f4"
down_revision: str | Sequence[str] | None = "d9a1b3c5e7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every legacy notification keeps its history; queued ones of a closed cycle are cancelled.
    op.execute(
        """
        INSERT INTO job_execution
            (job_type, chat_id, payload, dedup_key, state, execution_date, attempts, executed_at)
        SELECT 'training_reminder',
               c.chat_id,
               json_build_object('mesocycle_id', c.id),
               'training_reminder:' || c.id || ':' || n.occasion,
               CASE
                   WHEN n.state IN ('pending', 'sending') AND c.completed_at IS NULL THEN 'pending'
                   WHEN n.state = 'sent' THEN 'done'
                   WHEN n.state = 'failed' THEN 'failed'
                   ELSE 'cancelled'
               END,
               n.due_at,
               n.attempts,
               CASE WHEN n.state IN ('sent', 'failed') THEN n.due_at END
        FROM training_notifications n
        JOIN training_mesocycles c ON c.id = n.mesocycle_id
        """
    )
    # What enqueue_due would have created: a due reminder for dated cycles with none queued or sent.
    op.execute(
        """
        INSERT INTO job_execution
            (job_type, chat_id, payload, dedup_key, execution_date)
        SELECT 'training_reminder',
               c.chat_id,
               json_build_object('mesocycle_id', c.id),
               'training_reminder:' || c.id || ':' || (
                   SELECT count(*) FROM job_execution j
                   WHERE j.job_type = 'training_reminder'
                     AND (j.payload->>'mesocycle_id')::int = c.id
               ),
               c.expected_end_at
        FROM training_mesocycles c
        WHERE c.expected_end_at IS NOT NULL
          AND c.completed_at IS NULL
          AND c.reminders_enabled
          AND EXISTS (
              SELECT 1 FROM training_plans p
              JOIN training_sessions s ON s.current_plan_id = p.id
              WHERE p.mesocycle_id = c.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM job_execution j
              WHERE j.job_type = 'training_reminder'
                AND (j.payload->>'mesocycle_id')::int = c.id
                AND j.state IN ('pending', 'running', 'done')
          )
        """
    )
    # Future weeks only: past weeks are never asked retroactively.
    op.execute(
        """
        INSERT INTO job_execution (job_type, chat_id, payload, dedup_key, execution_date)
        SELECT 'evaluation_poll',
               c.chat_id,
               json_build_object('mesocycle_id', c.id, 'week_number', w.week),
               'evaluation_poll:' || c.id || ':' || w.week,
               c.started_at + w.week * interval '7 days'
        FROM training_mesocycles c
        CROSS JOIN generate_series(1, 4) AS w(week)
        WHERE c.started_at IS NOT NULL
          AND c.completed_at IS NULL
          AND c.started_at + w.week * interval '7 days' > now()
          AND EXISTS (
              SELECT 1 FROM training_plans p
              JOIN training_sessions s ON s.current_plan_id = p.id
              WHERE p.mesocycle_id = c.id
          )
        ON CONFLICT (dedup_key) DO NOTHING
        """
    )


def downgrade() -> None:
    # The schema revision drops job_execution; nothing to undo here.
    pass
