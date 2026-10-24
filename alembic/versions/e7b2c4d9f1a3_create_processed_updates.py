"""create processed updates

Deduplicates Telegram webhook re-deliveries by ``update_id``.

Revision ID: e7b2c4d9f1a3
Revises: d4f1a9b7c3e2
Create Date: 2026-10-01 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7b2c4d9f1a3"
down_revision: str | Sequence[str] | None = "d4f1a9b7c3e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "processed_updates",
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("update_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("processed_updates")
