"""add water_tracking_enabled to profiles

Revision ID: acf09202a4a9
Revises: 19d5485f6ff1
Create Date: 2026-09-08 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'acf09202a4a9'
down_revision = '19d5485f6ff1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('profiles', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'water_tracking_enabled',
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
    # Drop the server default once existing rows are backfilled so the
    # column behaves like the other boolean flags (Python-side default
    # only) — same two-step pattern as sync_workout_to_sheets (GYM-2).
    with op.batch_alter_table('profiles', schema=None) as batch_op:
        batch_op.alter_column('water_tracking_enabled', server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('profiles', schema=None) as batch_op:
        batch_op.drop_column('water_tracking_enabled')
