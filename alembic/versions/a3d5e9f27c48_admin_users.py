"""admin console: users.last_login_at and users.member_id

Revision ID: a3d5e9f27c48
Revises: f2c4d8e19b36
Create Date: 2026-10-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3d5e9f27c48"
down_revision: Union[str, Sequence[str], None] = "f2c4d8e19b36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("member_id", sa.Integer(), nullable=True))
    op.create_foreign_key("users_member_id_fkey", "users", "members", ["member_id"], ["id"], ondelete="SET NULL")
    op.create_index(
        "uq_users_member_id", "users", ["member_id"], unique=True, postgresql_where=sa.text("member_id IS NOT NULL")
    )


def downgrade() -> None:
    op.drop_index("uq_users_member_id", table_name="users")
    op.drop_constraint("users_member_id_fkey", "users", type_="foreignkey")
    op.drop_column("users", "member_id")
    op.drop_column("users", "last_login_at")
