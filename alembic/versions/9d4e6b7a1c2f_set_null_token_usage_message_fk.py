"""set token usage message foreign key to null on delete

Revision ID: 9d4e6b7a1c2f
Revises: 7287a3dffce8
Create Date: 2026-09-16

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9d4e6b7a1c2f"
down_revision: str | Sequence[str] | None = "7287a3dffce8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow conversation messages to be deleted without losing token usage."""
    op.drop_constraint(
        "token_usage_conversation_message_id_fkey",
        "token_usage",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "token_usage_conversation_message_id_fkey",
        "token_usage",
        "conversation_messages",
        ["conversation_message_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Restore the restrictive foreign key behavior."""
    op.drop_constraint(
        "token_usage_conversation_message_id_fkey",
        "token_usage",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "token_usage_conversation_message_id_fkey",
        "token_usage",
        "conversation_messages",
        ["conversation_message_id"],
        ["id"],
    )
