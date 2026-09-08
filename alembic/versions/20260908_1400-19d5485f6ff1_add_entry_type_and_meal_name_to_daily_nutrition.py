"""add entry_type and meal_name to daily_nutrition

Revision ID: 19d5485f6ff1
Revises: 71c3dca95ec4
Create Date: 2026-09-08 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '19d5485f6ff1'
down_revision = '71c3dca95ec4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('daily_nutrition', schema=None) as batch_op:
        batch_op.add_column(sa.Column('entry_type', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('meal_name', sa.String(length=255), nullable=True))

    # Backfill (GYM-21): same heuristic api_get_today_meals used to tell
    # meals from water entries apart (`water_ml == 0`) — this doesn't change
    # what any existing row counts as, it just makes the distinction an
    # explicit column instead of one inferred at query time.
    op.execute(
        "UPDATE daily_nutrition SET entry_type = "
        "CASE WHEN water_ml > 0 THEN 'water' ELSE 'meal' END"
    )

    with op.batch_alter_table('daily_nutrition', schema=None) as batch_op:
        batch_op.alter_column(
            'entry_type', existing_type=sa.String(length=10), nullable=False
        )
        batch_op.create_index(
            batch_op.f('ix_daily_nutrition_entry_type'), ['entry_type'], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table('daily_nutrition', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_daily_nutrition_entry_type'))
        batch_op.drop_column('meal_name')
        batch_op.drop_column('entry_type')
