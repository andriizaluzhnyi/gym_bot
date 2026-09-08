"""Tests for the GYM-21 data migration that backfills
``DailyNutrition.entry_type``
(``alembic/versions/20260908_1400-19d5485f6ff1_add_entry_type_and_meal_name_to_daily_nutrition.py``).

Runs the migration's ``upgrade()``/``downgrade()`` directly against a
throwaway sync SQLite connection, via a hand-wired Alembic ``Operations``
instance bound to that connection — not through ``alembic.command.upgrade()``
(which would walk the full revision chain; some earlier revisions import
``src.database``, which builds an async DB engine from ``DATABASE_URL`` at
*import* time — a different concern from what's being verified here).

The migration module's global ``op`` name (bound to the ``alembic.op``
proxy by its own ``from alembic import op``) is swapped for our real
``Operations`` instance before calling ``upgrade()``/``downgrade()``,
since driving the proxy's active-context stack correctly by hand — outside
of a real ``env.py`` run — turned out to be unreliable across Alembic's
batch-operations internals; assigning a real ``Operations`` object
directly sidesteps that path entirely while still exercising the exact
``op.batch_alter_table``/``op.execute`` calls the migration file contains.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION_PATH = (
    Path(__file__).parent.parent
    / "alembic" / "versions"
    / "20260908_1400-19d5485f6ff1_add_entry_type_and_meal_name_to_daily_nutrition.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("gym21_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_pre_migration_table(connection: sa.Connection) -> None:
    """The ``daily_nutrition`` schema as it existed just before this
    migration — no ``entry_type``/``meal_name`` yet.
    """
    connection.execute(sa.text("""
        CREATE TABLE daily_nutrition (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id CHAR(36) NOT NULL,
            date DATETIME NOT NULL,
            water_ml INTEGER,
            calories INTEGER,
            protein INTEGER,
            fats INTEGER,
            carbs INTEGER,
            created_at DATETIME,
            updated_at DATETIME
        )
    """))


def _insert_row(
    connection: sa.Connection, row_id: int, *,
    water_ml, calories=0, protein=0, fats=0, carbs=0,
) -> None:
    connection.execute(
        sa.text(
            "INSERT INTO daily_nutrition "
            "(id, user_id, date, water_ml, calories, protein, fats, carbs) "
            "VALUES (:id, 'u1', '2026-01-01 00:00:00', :water_ml, :calories, "
            ":protein, :fats, :carbs)"
        ),
        {
            "id": row_id, "water_ml": water_ml, "calories": calories,
            "protein": protein, "fats": fats, "carbs": carbs,
        },
    )


def _run(connection: sa.Connection, migration, direction: str) -> None:
    ctx = MigrationContext.configure(connection)
    migration.op = Operations(ctx)
    getattr(migration, direction)()


def _column_info(connection: sa.Connection) -> dict[str, int]:
    """Column name -> ``notnull`` flag (1/0), from ``PRAGMA table_info``."""
    rows = connection.execute(sa.text("PRAGMA table_info(daily_nutrition)")).fetchall()
    return {row[1]: row[3] for row in rows}


def _entry_types(connection: sa.Connection) -> dict[int, str]:
    rows = connection.execute(
        sa.text("SELECT id, entry_type FROM daily_nutrition ORDER BY id")
    ).fetchall()
    return {row[0]: row[1] for row in rows}


class TestBackfillsEntryType:
    def test_positive_water_ml_becomes_water(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _create_pre_migration_table(connection)
            _insert_row(connection, 1, water_ml=250)
            connection.commit()

            _run(connection, _load_migration(), "upgrade")

            assert _entry_types(connection)[1] == "water"

    def test_zero_water_ml_becomes_meal(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _create_pre_migration_table(connection)
            _insert_row(connection, 1, water_ml=0, calories=500)
            connection.commit()

            _run(connection, _load_migration(), "upgrade")

            assert _entry_types(connection)[1] == "meal"

    def test_null_water_ml_becomes_meal(self):
        """Matches the pre-migration heuristic (`water_ml == 0` filters
        meals in `api_get_today_meals`; SQL `NULL > 0` is falsy, so NULL
        rows fall to the same 'meal' branch as zero, same as `water_ml or
        0` reads them elsewhere in the app).
        """
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _create_pre_migration_table(connection)
            _insert_row(connection, 1, water_ml=None, calories=100)
            connection.commit()

            _run(connection, _load_migration(), "upgrade")

            assert _entry_types(connection)[1] == "meal"

    def test_does_not_change_existing_columns(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _create_pre_migration_table(connection)
            _insert_row(connection, 1, water_ml=250, calories=10, protein=1, fats=2, carbs=3)
            connection.commit()

            _run(connection, _load_migration(), "upgrade")

            row = connection.execute(
                sa.text(
                    "SELECT water_ml, calories, protein, fats, carbs "
                    "FROM daily_nutrition WHERE id = 1"
                )
            ).one()
            assert tuple(row) == (250, 10, 1, 2, 3)


class TestSchemaAfterUpgrade:
    def test_entry_type_is_not_null(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _create_pre_migration_table(connection)
            _insert_row(connection, 1, water_ml=100)
            connection.commit()

            _run(connection, _load_migration(), "upgrade")

            assert _column_info(connection)["entry_type"] == 1

    def test_meal_name_is_nullable(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _create_pre_migration_table(connection)
            connection.commit()

            _run(connection, _load_migration(), "upgrade")

            assert _column_info(connection)["meal_name"] == 0


class TestDowngrade:
    def test_removes_both_new_columns(self):
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.connect() as connection:
            _create_pre_migration_table(connection)
            _insert_row(connection, 1, water_ml=100)
            connection.commit()

            migration = _load_migration()
            _run(connection, migration, "upgrade")
            _run(connection, migration, "downgrade")

            columns = _column_info(connection)
            assert "entry_type" not in columns
            assert "meal_name" not in columns
