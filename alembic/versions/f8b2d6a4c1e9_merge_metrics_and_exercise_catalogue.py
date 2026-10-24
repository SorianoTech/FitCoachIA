"""Merge the metrics and exercise catalogue migration branches."""

from collections.abc import Sequence

revision: str = "f8b2d6a4c1e9"
down_revision: str | Sequence[str] | None = ("e5c7a9b1d3f4", "c7a9e2d4f6b1")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
