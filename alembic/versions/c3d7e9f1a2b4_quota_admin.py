"""Admin-configurable quotas (global and per-user) with an audit trail."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d7e9f1a2b4"
down_revision: str | Sequence[str] | None = "b82ac09d743f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "quota_configs",
        sa.Column("scope_id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("token_limit", sa.Integer(), nullable=False),
        sa.Column("soft_ratio", sa.Float(), nullable=False),
        sa.Column("window_minutes", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("scope_id >= 0", name="ck_quota_configs_scope_id"),
        sa.CheckConstraint(
            "token_limit > 0 AND token_limit <= 1000000000", name="ck_quota_configs_token_limit"
        ),
        sa.CheckConstraint(
            "soft_ratio > 0 AND soft_ratio <= 1", name="ck_quota_configs_soft_ratio"
        ),
        sa.CheckConstraint(
            "window_minutes > 0 AND window_minutes <= 525600",
            name="ck_quota_configs_window_minutes",
        ),
    )
    op.create_table(
        "quota_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True),
        sa.Column("after", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_quota_audit_subject_chat_id_id", "quota_audit", ["subject_chat_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_quota_audit_subject_chat_id_id", table_name="quota_audit")
    op.drop_table("quota_audit")
    op.drop_table("quota_configs")
