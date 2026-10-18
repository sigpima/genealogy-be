"""a Google Maps link for a burial and for a place

Revision ID: e7b9c3d61a82
Revises: d6a8b2c50f71
Create Date: 2026-10-19 09:00:00
"""

import sqlalchemy as sa
from alembic import op

revision = "e7b9c3d61a82"
down_revision = "d6a8b2c50f71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("members", sa.Column("burial_map_url", sa.String(length=500), nullable=True))
    op.add_column("places", sa.Column("map_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("places", "map_url")
    op.drop_column("members", "burial_map_url")
