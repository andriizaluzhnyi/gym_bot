"""add sync_workout_to_sheets to users

Revision ID: 69a5f433a713
Revises: be2c6dd34b6f
Create Date: 2026-09-07 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '69a5f433a713'
down_revision = 'be2c6dd34b6f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'sync_workout_to_sheets',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    # Drop the server default once existing rows are backfilled so the
    # column behaves like the other boolean flags (Python-side default only).
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('sync_workout_to_sheets', server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('sync_workout_to_sheets')
