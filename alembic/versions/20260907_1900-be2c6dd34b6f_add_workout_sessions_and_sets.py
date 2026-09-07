"""add workout sessions and sets

Revision ID: be2c6dd34b6f
Revises: d5844aba1d29
Create Date: 2026-09-07 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

from src.database import models


# revision identifiers, used by Alembic.
revision = 'be2c6dd34b6f'
down_revision = 'd5844aba1d29'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'workout_sessions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', models.GUID(), nullable=False),
        sa.Column('day', sa.Integer(), nullable=True),
        sa.Column('muscle_group', sa.String(length=255), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('performed_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('workout_sessions', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_workout_sessions_user_id'), ['user_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_workout_sessions_performed_at'), ['performed_at'], unique=False
        )
        batch_op.create_index(
            'ix_workout_sessions_user_id_performed_at',
            ['user_id', 'performed_at'],
            unique=False,
        )

    op.create_table(
        'workout_sets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('user_id', models.GUID(), nullable=False),
        sa.Column('exercise_name', sa.String(length=255), nullable=False),
        sa.Column('muscle_group', sa.String(length=255), nullable=True),
        sa.Column('set_number', sa.Integer(), nullable=False),
        sa.Column('weight', sa.Float(), nullable=False),
        sa.Column('reps', sa.Integer(), nullable=False),
        sa.Column('planned_sets_reps', sa.String(length=50), nullable=True),
        sa.Column('performed_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['workout_sessions.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('workout_sets', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_workout_sets_session_id'), ['session_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_workout_sets_user_id'), ['user_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_workout_sets_performed_at'), ['performed_at'], unique=False
        )
        batch_op.create_index(
            'ix_workout_sets_user_id_exercise_name_performed_at',
            ['user_id', 'exercise_name', 'performed_at'],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('workout_sets', schema=None) as batch_op:
        batch_op.drop_index('ix_workout_sets_user_id_exercise_name_performed_at')
        batch_op.drop_index(batch_op.f('ix_workout_sets_performed_at'))
        batch_op.drop_index(batch_op.f('ix_workout_sets_user_id'))
        batch_op.drop_index(batch_op.f('ix_workout_sets_session_id'))

    op.drop_table('workout_sets')

    with op.batch_alter_table('workout_sessions', schema=None) as batch_op:
        batch_op.drop_index('ix_workout_sessions_user_id_performed_at')
        batch_op.drop_index(batch_op.f('ix_workout_sessions_performed_at'))
        batch_op.drop_index(batch_op.f('ix_workout_sessions_user_id'))

    op.drop_table('workout_sessions')
