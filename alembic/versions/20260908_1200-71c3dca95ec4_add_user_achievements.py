"""add user_achievements

Revision ID: 71c3dca95ec4
Revises: a3f6c9e2b184
Create Date: 2026-09-08 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

from src.database import models


# revision identifiers, used by Alembic.
revision = '71c3dca95ec4'
down_revision = 'a3f6c9e2b184'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'user_achievements',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', models.GUID(), nullable=False),
        sa.Column('achievement_code', sa.String(length=50), nullable=False),
        sa.Column('unlocked_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('user_achievements', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_user_achievements_user_id'), ['user_id'], unique=False
        )
        batch_op.create_index(
            'ix_user_achievements_user_id_achievement_code',
            ['user_id', 'achievement_code'],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table('user_achievements', schema=None) as batch_op:
        batch_op.drop_index('ix_user_achievements_user_id_achievement_code')
        batch_op.drop_index(batch_op.f('ix_user_achievements_user_id'))

    op.drop_table('user_achievements')
