"""add stripe billing sync fields

Revision ID: b8f9c7e1a2d4
Revises: 7387fdb14809
Create Date: 2026-02-23 15:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8f9c7e1a2d4'
down_revision = '7387fdb14809'
branch_labels = None
depends_on = None


def _table_exists(inspector, table_name):
    return table_name in inspector.get_table_names()


def _column_exists(inspector, table_name, column_name):
    if not _table_exists(inspector, table_name):
        return False
    return any(column['name'] == column_name for column in inspector.get_columns(table_name))


def _index_exists(inspector, table_name, index_name):
    if not _table_exists(inspector, table_name):
        return False
    return any(index['name'] == index_name for index in inspector.get_indexes(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _column_exists(inspector, 'users', 'stripe_customer_id'):
        op.add_column('users', sa.Column('stripe_customer_id', sa.String(length=255), nullable=True))
        inspector = sa.inspect(bind)

    if not _column_exists(inspector, 'users', 'stripe_subscription_id'):
        op.add_column('users', sa.Column('stripe_subscription_id', sa.String(length=255), nullable=True))
        inspector = sa.inspect(bind)

    if not _column_exists(inspector, 'users', 'billing_status'):
        op.add_column(
            'users',
            sa.Column(
                'billing_status',
                sa.String(length=32),
                nullable=False,
                server_default='inactive',
            ),
        )
        inspector = sa.inspect(bind)

    users_customer_index = op.f('ix_users_stripe_customer_id')
    if not _index_exists(inspector, 'users', users_customer_index):
        op.create_index(users_customer_index, 'users', ['stripe_customer_id'], unique=True)
        inspector = sa.inspect(bind)

    users_subscription_index = op.f('ix_users_stripe_subscription_id')
    if not _index_exists(inspector, 'users', users_subscription_index):
        op.create_index(users_subscription_index, 'users', ['stripe_subscription_id'], unique=True)
        inspector = sa.inspect(bind)

    if not _table_exists(inspector, 'stripe_webhook_events'):
        op.create_table(
            'stripe_webhook_events',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('event_id', sa.String(length=255), nullable=False),
            sa.Column('event_type', sa.String(length=120), nullable=False),
            sa.Column('processed_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('event_id'),
        )
        inspector = sa.inspect(bind)

    events_index = op.f('ix_stripe_webhook_events_event_id')
    if not _index_exists(inspector, 'stripe_webhook_events', events_index):
        op.create_index(events_index, 'stripe_webhook_events', ['event_id'], unique=True)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    events_index = op.f('ix_stripe_webhook_events_event_id')
    if _index_exists(inspector, 'stripe_webhook_events', events_index):
        op.drop_index(events_index, table_name='stripe_webhook_events')
        inspector = sa.inspect(bind)

    if _table_exists(inspector, 'stripe_webhook_events'):
        op.drop_table('stripe_webhook_events')
        inspector = sa.inspect(bind)

    users_subscription_index = op.f('ix_users_stripe_subscription_id')
    if _index_exists(inspector, 'users', users_subscription_index):
        op.drop_index(users_subscription_index, table_name='users')
        inspector = sa.inspect(bind)

    users_customer_index = op.f('ix_users_stripe_customer_id')
    if _index_exists(inspector, 'users', users_customer_index):
        op.drop_index(users_customer_index, table_name='users')
        inspector = sa.inspect(bind)

    if _column_exists(inspector, 'users', 'billing_status'):
        op.drop_column('users', 'billing_status')
        inspector = sa.inspect(bind)
    if _column_exists(inspector, 'users', 'stripe_subscription_id'):
        op.drop_column('users', 'stripe_subscription_id')
        inspector = sa.inspect(bind)
    if _column_exists(inspector, 'users', 'stripe_customer_id'):
        op.drop_column('users', 'stripe_customer_id')
