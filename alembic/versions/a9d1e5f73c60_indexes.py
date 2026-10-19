"""index the children of a person and the per-family newest-first log

Revision ID: a9d1e5f73c60
Revises: f8c0d4e72b93
Create Date: 2026-10-20 09:00:00
"""

from alembic import op

revision = "a9d1e5f73c60"
down_revision = "f8c0d4e72b93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_members_parent_id", "members", ["parent_id"])
    op.create_index("ix_audit_log_tree_id_id", "audit_log", ["tree_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_tree_id_id", table_name="audit_log")
    op.drop_index("ix_members_parent_id", table_name="members")
