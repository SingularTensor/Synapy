"""add user lives columns

Revision ID: c1d3a7b9e5f2
Revises: b8f9c7e1a2d4
Create Date: 2026-02-23 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c1d3a7b9e5f2'
down_revision = 'b8f9c7e1a2d4'
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    if table_name not in inspector.get_table_names():
        return False
    return any(column['name'] == column_name for column in inspector.get_columns(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _column_exists(inspector, 'users', 'lives_remaining'):
        op.add_column(
            'users',
            sa.Column('lives_remaining', sa.Integer(), nullable=False, server_default='8'),
        )
        inspector = sa.inspect(bind)

    if not _column_exists(inspector, 'users', 'lives_last_updated_at'):
        op.add_column('users', sa.Column('lives_last_updated_at', sa.DateTime(), nullable=True))

    op.execute("UPDATE users SET lives_last_updated_at = CURRENT_TIMESTAMP WHERE lives_last_updated_at IS NULL")


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _column_exists(inspector, 'users', 'lives_last_updated_at'):
        op.drop_column('users', 'lives_last_updated_at')
        inspector = sa.inspect(bind)

    if _column_exists(inspector, 'users', 'lives_remaining'):
        op.drop_column('users', 'lives_remaining')
