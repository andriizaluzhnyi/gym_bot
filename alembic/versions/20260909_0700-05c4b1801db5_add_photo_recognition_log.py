"""add photo_recognition_log

Revision ID: 05c4b1801db5
Revises: 2b10cd32f6f1
Create Date: 2026-09-09 07:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

from src.database import models


# revision identifiers, used by Alembic.
revision = '05c4b1801db5'
down_revision = '2b10cd32f6f1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'photo_recognition_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', models.GUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('photo_recognition_log', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_photo_recognition_log_user_id'), ['user_id'], unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_photo_recognition_log_created_at'), ['created_at'], unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('photo_recognition_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_photo_recognition_log_created_at'))
        batch_op.drop_index(batch_op.f('ix_photo_recognition_log_user_id'))

    op.drop_table('photo_recognition_log')
