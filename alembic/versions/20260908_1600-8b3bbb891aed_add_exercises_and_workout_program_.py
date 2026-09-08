"""add exercises and workout_program_exercises

Revision ID: 8b3bbb891aed
Revises: acf09202a4a9
Create Date: 2026-09-08 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

from src.database import models


# revision identifiers, used by Alembic.
revision = '8b3bbb891aed'
down_revision = 'acf09202a4a9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'exercises',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('normalized_name', sa.String(length=255), nullable=False),
        sa.Column('muscle_group', sa.String(length=255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('image_url', sa.String(length=500), nullable=True),
        sa.Column('video_url', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('exercises', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_exercises_normalized_name'),
            ['normalized_name'], unique=True,
        )

    op.create_table(
        'workout_program_exercises',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', models.GUID(), nullable=False),
        sa.Column('day', sa.Integer(), nullable=False),
        sa.Column('muscle_group', sa.String(length=255), nullable=False),
        sa.Column('exercise_id', sa.Integer(), nullable=False),
        sa.Column('exercise_name', sa.String(length=255), nullable=False),
        sa.Column('sets_reps', sa.String(length=50), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['exercise_id'], ['exercises.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('workout_program_exercises', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_workout_program_exercises_user_id'), ['user_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_workout_program_exercises_exercise_id'), ['exercise_id'], unique=False
        )
        batch_op.create_index(
            'ix_workout_program_exercises_user_id_day_position',
            ['user_id', 'day', 'position'],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('workout_program_exercises', schema=None) as batch_op:
        batch_op.drop_index('ix_workout_program_exercises_user_id_day_position')
        batch_op.drop_index(batch_op.f('ix_workout_program_exercises_exercise_id'))
        batch_op.drop_index(batch_op.f('ix_workout_program_exercises_user_id'))

    op.drop_table('workout_program_exercises')

    with op.batch_alter_table('exercises', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_exercises_normalized_name'))

    op.drop_table('exercises')
