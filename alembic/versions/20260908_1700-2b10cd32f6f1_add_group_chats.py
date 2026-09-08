"""add group_chats

Revision ID: 2b10cd32f6f1
Revises: 8b3bbb891aed
Create Date: 2026-09-08 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2b10cd32f6f1'
down_revision = '8b3bbb891aed'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'group_chats',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('added_by_telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('remind_nutrition', sa.Boolean(), nullable=False),
        sa.Column('nutrition_time', sa.String(length=5), nullable=False),
        sa.Column('remind_measurements', sa.Boolean(), nullable=False),
        sa.Column('measurements_weekday', sa.Integer(), nullable=False),
        sa.Column('measurements_time', sa.String(length=5), nullable=False),
        sa.Column('remind_photos', sa.Boolean(), nullable=False),
        sa.Column('photos_day_of_month', sa.Integer(), nullable=False),
        sa.Column('photos_time', sa.String(length=5), nullable=False),
        sa.Column('last_nutrition_sent_on', sa.Date(), nullable=True),
        sa.Column('last_measurements_sent_on', sa.Date(), nullable=True),
        sa.Column('last_photos_sent_on', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('group_chats', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_group_chats_chat_id'), ['chat_id'], unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table('group_chats', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_group_chats_chat_id'))

    op.drop_table('group_chats')
