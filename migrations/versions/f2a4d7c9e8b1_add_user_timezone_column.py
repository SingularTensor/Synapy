"""add user timezone column

Revision ID: f2a4d7c9e8b1
Revises: c1d3a7b9e5f2
Create Date: 2026-02-23 23:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f2a4d7c9e8b1'
down_revision = 'c1d3a7b9e5f2'
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    if table_name not in inspector.get_table_names():
        return False
    return any(column['name'] == column_name for column in inspector.get_columns(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _column_exists(inspector, 'users', 'timezone'):
        op.add_column('users', sa.Column('timezone', sa.String(length=64), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _column_exists(inspector, 'users', 'timezone'):
        op.drop_column('users', 'timezone')
