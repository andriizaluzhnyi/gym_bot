"""add completed_at to workout_sessions

Revision ID: a3f6c9e2b184
Revises: 69a5f433a713
Create Date: 2026-09-07 20:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3f6c9e2b184'
down_revision = '69a5f433a713'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('workout_sessions', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('completed_at', sa.DateTime(), nullable=True)
        )

    # Every session created before GYM-2c was written atomically at the end
    # of the workout (the old one-shot save), so it was already "complete" —
    # backfill completed_at from performed_at so these don't look like
    # abandoned drafts.
    op.execute(
        "UPDATE workout_sessions SET completed_at = performed_at "
        "WHERE completed_at IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table('workout_sessions', schema=None) as batch_op:
        batch_op.drop_column('completed_at')
