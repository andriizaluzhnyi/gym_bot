"""Tests for the GYM-32 migration that creates ``group_chats``
(``alembic/versions/20260908_1700-2b10cd32f6f1_add_group_chats.py``).

Same hand-wired-``Operations`` harness as
``tests/test_migration_nutrition_entry_type.py`` — see that file's
module docstring for why this doesn't go through
``alembic.command.upgrade()``.
"""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).parent.parent
    / "alembic" / "versions"
    / "20260908_1700-2b10cd32f6f1_add_group_chats.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("gym32_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(connection: sa.Connection, migration, direction: str) -> None:
    ctx = MigrationContext.configure(connection)
    migration.op = Operations(ctx)
    getattr(migration, direction)()


def _table_names(connection: sa.Connection) -> set[str]:
    rows = connection.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='table'")
    ).fetchall()
    return {row[0] for row in rows}


def _column_info(connection: sa.Connection) -> dict[str, dict]:
    """Column name -> {"notnull": 0/1, "type": str}, from PRAGMA table_info."""
    rows = connection.execute(sa.text("PRAGMA table_info(group_chats)")).fetchall()
    return {row[1]: {"notnull": row[3], "type": row[2]} for row in rows}


def _index_names(connection: sa.Connection) -> set[str]:
    rows = connection.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='group_chats'")
    ).fetchall()
    return {row[0] for row in rows}


class TestUpgrade:
    def test_creates_group_chats_table(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _run(connection, _load_migration(), "upgrade")
            assert "group_chats" in _table_names(connection)

    def test_all_expected_columns_present(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _run(connection, _load_migration(), "upgrade")
            columns = _column_info(connection)
            assert set(columns) == {
                "id", "chat_id", "title", "is_active", "added_by_telegram_id",
                "remind_nutrition", "nutrition_time", "remind_measurements",
                "measurements_weekday", "measurements_time", "remind_photos",
                "photos_day_of_month", "photos_time", "last_nutrition_sent_on",
                "last_measurements_sent_on", "last_photos_sent_on",
                "created_at", "updated_at",
            }

    def test_required_columns_are_not_null(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _run(connection, _load_migration(), "upgrade")
            columns = _column_info(connection)
            for name in [
                "chat_id", "is_active", "added_by_telegram_id",
                "remind_nutrition", "nutrition_time", "remind_measurements",
                "measurements_weekday", "measurements_time", "remind_photos",
                "photos_day_of_month", "photos_time", "created_at", "updated_at",
            ]:
                assert columns[name]["notnull"] == 1, f"{name} should be NOT NULL"

    def test_last_sent_columns_are_nullable(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _run(connection, _load_migration(), "upgrade")
            columns = _column_info(connection)
            for name in [
                "last_nutrition_sent_on", "last_measurements_sent_on",
                "last_photos_sent_on",
            ]:
                assert columns[name]["notnull"] == 0, f"{name} should be nullable"

    def test_chat_id_has_a_unique_index(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _run(connection, _load_migration(), "upgrade")
            assert "ix_group_chats_chat_id" in _index_names(connection)

            connection.execute(sa.text(
                "INSERT INTO group_chats "
                "(chat_id, is_active, added_by_telegram_id, remind_nutrition, "
                "nutrition_time, remind_measurements, measurements_weekday, "
                "measurements_time, remind_photos, photos_day_of_month, "
                "photos_time, created_at, updated_at) VALUES "
                "(-100, 1, 1, 1, '20:00', 1, 0, '09:00', 0, 1, '09:00', "
                "'2026-01-01', '2026-01-01')"
            ))
            connection.commit()

            with pytest.raises(sa.exc.IntegrityError):
                connection.execute(sa.text(
                    "INSERT INTO group_chats "
                    "(chat_id, is_active, added_by_telegram_id, remind_nutrition, "
                    "nutrition_time, remind_measurements, measurements_weekday, "
                    "measurements_time, remind_photos, photos_day_of_month, "
                    "photos_time, created_at, updated_at) VALUES "
                    "(-100, 1, 2, 1, '20:00', 1, 0, '09:00', 0, 1, '09:00', "
                    "'2026-01-01', '2026-01-01')"
                ))


class TestDowngrade:
    def test_drops_group_chats_table(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            migration = _load_migration()
            _run(connection, migration, "upgrade")
            _run(connection, migration, "downgrade")
            assert "group_chats" not in _table_names(connection)
