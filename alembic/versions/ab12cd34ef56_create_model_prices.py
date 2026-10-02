"""create model prices

Revision ID: ab12cd34ef56
Revises: 9d4e6b7a1c2f
Create Date: 2026-09-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ab12cd34ef56"
down_revision: str | Sequence[str] | None = "9d4e6b7a1c2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the model price catalog and seed the configured development model."""
    op.create_table(
        "model_prices",
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("input_usd_per_million", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("output_usd_per_million", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("model"),
    )
    op.bulk_insert(
        sa.table(
            "model_prices",
            sa.column("model", sa.String),
            sa.column("input_usd_per_million", sa.Numeric),
            sa.column("output_usd_per_million", sa.Numeric),
            sa.column("source", sa.String),
        ),
        [
            {
                "model": "gpt-5-nano-2025-08-07",
                "input_usd_per_million": 0.05,
                "output_usd_per_million": 0.40,
                "source": "https://developers.openai.com/api/docs/pricing",
            }
        ],
    )


def downgrade() -> None:
    """Drop the model price catalog."""
    op.drop_table("model_prices")
