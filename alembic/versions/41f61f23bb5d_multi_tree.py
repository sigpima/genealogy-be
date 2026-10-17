"""multi tree

Revision ID: 41f61f23bb5d
Revises: c1a1a4ec7e42
Create Date: 2026-10-17 22:50:12.439509

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '41f61f23bb5d'
down_revision: Union[str, Sequence[str], None] = 'c1a1a4ec7e42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: every family gets its own tree; existing data moves into one default tree."""
    op.create_table(
        'trees',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=60), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_trees_slug'), 'trees', ['slug'], unique=True)

    # Data that already exists belongs to one default tree (a fresh database gets no tree here: the
    # first registration creates it).
    op.execute(
        "INSERT INTO trees (name, slug) SELECT 'Gia phả', 'default' "
        "WHERE EXISTS (SELECT 1 FROM members) OR EXISTS (SELECT 1 FROM users)"
    )

    op.add_column('members', sa.Column('tree_id', sa.Integer(), nullable=True))
    op.execute("UPDATE members SET tree_id = (SELECT MIN(id) FROM trees)")
    op.alter_column('members', 'tree_id', nullable=False)
    op.create_index(op.f('ix_members_tree_id'), 'members', ['tree_id'], unique=False)
    op.create_foreign_key('members_tree_id_fkey', 'members', 'trees', ['tree_id'], ['id'])

    op.add_column('users', sa.Column('tree_id', sa.Integer(), nullable=True))
    op.execute("UPDATE users SET tree_id = (SELECT MIN(id) FROM trees)")
    op.create_index(op.f('ix_users_tree_id'), 'users', ['tree_id'], unique=False)
    op.create_foreign_key('users_tree_id_fkey', 'users', 'trees', ['tree_id'], ['id'])

    # Settings become per tree: primary key (tree_id, key).
    op.add_column('site_settings', sa.Column('tree_id', sa.Integer(), nullable=True))
    op.execute("UPDATE site_settings SET tree_id = (SELECT MIN(id) FROM trees)")
    op.execute("DELETE FROM site_settings WHERE tree_id IS NULL")
    op.alter_column('site_settings', 'tree_id', nullable=False)
    op.drop_constraint('site_settings_pkey', 'site_settings', type_='primary')
    op.create_primary_key('site_settings_pkey', 'site_settings', ['tree_id', 'key'])
    op.create_foreign_key(
        'site_settings_tree_id_fkey', 'site_settings', 'trees', ['tree_id'], ['id'], ondelete='CASCADE'
    )


def downgrade() -> None:
    """Downgrade schema (best effort: with several trees, per-tree settings collapse to one value per key)."""
    op.drop_constraint('site_settings_tree_id_fkey', 'site_settings', type_='foreignkey')
    op.drop_constraint('site_settings_pkey', 'site_settings', type_='primary')
    op.execute(
        "DELETE FROM site_settings a USING site_settings b "
        "WHERE a.key = b.key AND a.tree_id > b.tree_id"
    )
    op.drop_column('site_settings', 'tree_id')
    op.create_primary_key('site_settings_pkey', 'site_settings', ['key'])

    op.drop_constraint('users_tree_id_fkey', 'users', type_='foreignkey')
    op.drop_index(op.f('ix_users_tree_id'), table_name='users')
    op.drop_column('users', 'tree_id')

    op.drop_constraint('members_tree_id_fkey', 'members', type_='foreignkey')
    op.drop_index(op.f('ix_members_tree_id'), table_name='members')
    op.drop_column('members', 'tree_id')

    op.drop_index(op.f('ix_trees_slug'), table_name='trees')
    op.drop_table('trees')
