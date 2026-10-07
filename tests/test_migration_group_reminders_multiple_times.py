"""Tests for the migration that lets group reminders have any number of
daily slots (``alembic/versions/20261007_1800-c7e1d2a9f4b3_...``).

Same hand-wired-``Operations`` harness as
``tests/test_migration_group_chats.py``: the GYM-32 migration creates
``group_chats`` first, then this one is applied on top.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

VERSIONS = Path(__file__).parent.parent / "alembic" / "versions"
BASE_MIGRATION = VERSIONS / "20260908_1700-2b10cd32f6f1_add_group_chats.py"
MIGRATION = VERSIONS / "20261007_1800-c7e1d2a9f4b3_group_reminders_multiple_times.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(connection: sa.Connection, migration, direction: str) -> None:
    ctx = MigrationContext.configure(connection)
    migration.op = Operations(ctx)
    getattr(migration, direction)()


def _columns(connection: sa.Connection) -> set[str]:
    rows = connection.execute(sa.text("PRAGMA table_info(group_chats)")).fetchall()
    return {row[1] for row in rows}


def _insert_group(connection: sa.Connection, *, last_nutrition_sent_on=None) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO group_chats "
            "(chat_id, is_active, added_by_telegram_id, remind_nutrition, "
            "nutrition_time, remind_measurements, measurements_weekday, "
            "measurements_time, remind_photos, photos_day_of_month, "
            "photos_time, last_nutrition_sent_on, created_at, updated_at) VALUES "
            "(-100, 1, 1, 1, '20:00', 1, 0, '09:00', 0, 1, '09:00', :sent_on, "
            "'2026-01-01', '2026-01-01')"
        ),
        {"sent_on": last_nutrition_sent_on},
    )


def _upgraded(connection: sa.Connection, **row):
    _run(connection, _load(BASE_MIGRATION, "gym32_base"), "upgrade")
    _insert_group(connection, **row)
    migration = _load(MIGRATION, "multi_times")
    _run(connection, migration, "upgrade")
    return migration


class TestUpgrade:
    def test_replaces_sent_on_with_sent_at(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _upgraded(connection)
            columns = _columns(connection)
            for kind in ("nutrition", "measurements", "photos"):
                assert f"last_{kind}_sent_at" in columns
                assert f"last_{kind}_sent_on" not in columns

    def test_existing_sent_on_becomes_end_of_that_day(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _upgraded(connection, last_nutrition_sent_on="2026-06-15")
            value = connection.execute(
                sa.text("SELECT last_nutrition_sent_at FROM group_chats")
            ).scalar_one()
            assert str(value).startswith("2026-06-15 23:59:59")

    def test_time_columns_hold_a_list(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _upgraded(connection)
            connection.execute(sa.text(
                "UPDATE group_chats SET nutrition_time = '08:00,13:30,20:00'"
            ))
            value = connection.execute(
                sa.text("SELECT nutrition_time FROM group_chats")
            ).scalar_one()
            assert value == "08:00,13:30,20:00"


class TestDowngrade:
    def test_restores_single_time_and_sent_on(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            migration = _upgraded(connection)
            connection.execute(sa.text(
                "UPDATE group_chats SET nutrition_time = '13:30,08:00', "
                "last_nutrition_sent_at = '2026-06-15 13:30:00'"
            ))
            _run(connection, migration, "downgrade")

            columns = _columns(connection)
            assert "last_nutrition_sent_on" in columns
            assert "last_nutrition_sent_at" not in columns
            row = connection.execute(sa.text(
                "SELECT nutrition_time, last_nutrition_sent_on FROM group_chats"
            )).one()
            assert row[0] == "08:00"
            assert str(row[1]) == "2026-06-15"
