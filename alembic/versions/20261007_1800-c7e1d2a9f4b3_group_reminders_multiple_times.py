"""group reminders: any time, several per day

Widens ``group_chats.{nutrition,measurements,photos}_time`` from a single
``"HH:MM"`` (String(5)) to a comma-separated list (String(255)), and
replaces the per-day ``last_*_sent_on`` (Date) markers with
``last_*_sent_at`` (DateTime, local wall-clock) — a date alone can't tell
which of several same-day slots already fired.

Existing ``last_*_sent_on`` values are carried over as the *end* of that
day (23:59:59), so nothing already sent today is sent again.

Revision ID: c7e1d2a9f4b3
Revises: 05c4b1801db5
Create Date: 2026-10-07 18:00:00.000000

"""
from datetime import date, datetime, time

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7e1d2a9f4b3'
down_revision = '05c4b1801db5'
branch_labels = None
depends_on = None

_TYPES = ("nutrition", "measurements", "photos")


def _as_date(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])  # SQLite returns strings


def _as_datetime(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def upgrade() -> None:
    with op.batch_alter_table('group_chats', schema=None) as batch_op:
        for kind in _TYPES:
            batch_op.alter_column(
                f'{kind}_time',
                existing_type=sa.String(length=5),
                type_=sa.String(length=255),
                existing_nullable=False,
            )
            batch_op.add_column(
                sa.Column(f'last_{kind}_sent_at', sa.DateTime(), nullable=True)
            )

    conn = op.get_bind()
    group_chats = sa.table(
        'group_chats',
        sa.column('id', sa.Integer()),
        *[sa.column(f'last_{k}_sent_on', sa.Date()) for k in _TYPES],
        *[sa.column(f'last_{k}_sent_at', sa.DateTime()) for k in _TYPES],
    )
    rows = conn.execute(
        sa.select(group_chats.c.id, *[group_chats.c[f'last_{k}_sent_on'] for k in _TYPES])
    ).fetchall()
    for row in rows:
        values = {}
        for i, kind in enumerate(_TYPES, start=1):
            sent_on = _as_date(row[i])
            if sent_on is not None:
                values[f'last_{kind}_sent_at'] = datetime.combine(sent_on, time(23, 59, 59))
        if values:
            conn.execute(
                sa.update(group_chats).where(group_chats.c.id == row[0]).values(**values)
            )

    with op.batch_alter_table('group_chats', schema=None) as batch_op:
        for kind in _TYPES:
            batch_op.drop_column(f'last_{kind}_sent_on')


def downgrade() -> None:
    with op.batch_alter_table('group_chats', schema=None) as batch_op:
        for kind in _TYPES:
            batch_op.add_column(
                sa.Column(f'last_{kind}_sent_on', sa.Date(), nullable=True)
            )

    conn = op.get_bind()
    group_chats = sa.table(
        'group_chats',
        sa.column('id', sa.Integer()),
        *[sa.column(f'{k}_time', sa.String()) for k in _TYPES],
        *[sa.column(f'last_{k}_sent_on', sa.Date()) for k in _TYPES],
        *[sa.column(f'last_{k}_sent_at', sa.DateTime()) for k in _TYPES],
    )
    rows = conn.execute(
        sa.select(
            group_chats.c.id,
            *[group_chats.c[f'{k}_time'] for k in _TYPES],
            *[group_chats.c[f'last_{k}_sent_at'] for k in _TYPES],
        )
    ).fetchall()
    n = len(_TYPES)
    for row in rows:
        values = {}
        for i, kind in enumerate(_TYPES):
            # Only one time fits in String(5) — keep the earliest slot.
            times = sorted(t.strip() for t in (row[1 + i] or "").split(",") if t.strip())
            values[f'{kind}_time'] = times[0] if times else "09:00"
            sent_at = _as_datetime(row[1 + n + i])
            values[f'last_{kind}_sent_on'] = sent_at.date() if sent_at else None
        conn.execute(
            sa.update(group_chats).where(group_chats.c.id == row[0]).values(**values)
        )

    with op.batch_alter_table('group_chats', schema=None) as batch_op:
        for kind in _TYPES:
            batch_op.drop_column(f'last_{kind}_sent_at')
            batch_op.alter_column(
                f'{kind}_time',
                existing_type=sa.String(length=255),
                type_=sa.String(length=5),
                existing_nullable=False,
            )
