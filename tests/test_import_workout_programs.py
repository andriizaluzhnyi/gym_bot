"""Tests for GYM-29: scripts/import_workout_programs.py.

``parse_program_row``/``group_rows_by_day`` are pure functions, tested
directly against plain dicts. ``import_user``/``run`` are exercised
against the real (SQLite, per ``tests/conftest.py``) DB with
``GoogleSheetsService`` mocked, to cover idempotency and the
no-matching-DB-user report path.
"""

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from scripts.import_workout_programs import (
    group_rows_by_day,
    import_user,
    parse_program_row,
    run,
)
from src.database.models import Base
from src.database.repository import UserRepository, WorkoutProgramRepository
from src.database.session import async_session_maker, engine

TZ = "Europe/Kyiv"  # winter offset UTC+2, matches settings.timezone default


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _make_user(username: str, telegram_id: int):
    async with async_session_maker() as session:
        user, _ = await UserRepository(session).get_or_create(
            telegram_id=telegram_id, first_name="Test", username=username
        )
        await session.commit()
        return user


SHEET_ROW = {
    "day": "1",
    "muscle_group": "🏋️ Груди",
    "exercise": "Жим лежачи",
    "sets_reps": "3/10",
    "comment": "повільно",
    "created_at": "07.01.2026 10:00",
}


class TestParseProgramRow:
    def test_parses_fields_and_converts_local_date_to_utc(self):
        item = parse_program_row(SHEET_ROW, tz_name=TZ)

        assert item["exercise"] == "Жим лежачи"
        assert item["muscle_group"] == "🏋️ Груди"
        assert item["sets_reps"] == "3/10"
        assert item["comment"] == "повільно"
        # 10:00 Kyiv (winter, UTC+2) -> 08:00 UTC.
        assert item["created_at_utc"] == datetime(2026, 1, 7, 8, 0)

    def test_missing_comment_becomes_empty_string(self):
        row = {**SHEET_ROW, "comment": ""}
        item = parse_program_row(row, tz_name=TZ)
        assert item["comment"] == ""

    def test_unparseable_date_falls_back_to_now(self):
        row = {**SHEET_ROW, "created_at": "not a date"}
        fallback = datetime(2026, 5, 1, 12, 0)
        item = parse_program_row(row, tz_name=TZ, now=fallback)
        assert item["created_at_utc"] == fallback

    def test_missing_date_falls_back_to_now(self):
        row = {**SHEET_ROW, "created_at": ""}
        fallback = datetime(2026, 5, 1, 12, 0)
        item = parse_program_row(row, tz_name=TZ, now=fallback)
        assert item["created_at_utc"] == fallback

    def test_unparseable_date_without_explicit_now_uses_utcnow(self):
        row = {**SHEET_ROW, "created_at": "garbage"}
        item = parse_program_row(row, tz_name=TZ)
        # Just confirm it's a real, recent datetime, not the fallback path
        # throwing — exact value depends on wall-clock time.
        assert isinstance(item["created_at_utc"], datetime)


class TestGroupRowsByDay:
    def test_groups_and_preserves_order_within_a_day(self):
        rows = [
            {**SHEET_ROW, "day": "1", "exercise": "A"},
            {**SHEET_ROW, "day": "2", "exercise": "B"},
            {**SHEET_ROW, "day": "1", "exercise": "C"},
        ]
        grouped = group_rows_by_day(rows)

        assert set(grouped) == {1, 2}
        assert [r["exercise"] for r in grouped[1]] == ["A", "C"]
        assert [r["exercise"] for r in grouped[2]] == ["B"]

    def test_blank_day_defaults_to_one(self):
        rows = [{**SHEET_ROW, "day": ""}]
        grouped = group_rows_by_day(rows)
        assert set(grouped) == {1}

    def test_unparseable_day_defaults_to_one(self):
        rows = [{**SHEET_ROW, "day": "не число"}]
        grouped = group_rows_by_day(rows)
        assert set(grouped) == {1}


def _mock_sheets(programs: list[dict]) -> AsyncMock:
    sheets = AsyncMock()
    sheets.get_workout_programs = AsyncMock(return_value=programs)
    return sheets


class TestImportUser:
    async def test_imports_rows_preserving_order_and_created_at(self):
        user = await _make_user("lifter", telegram_id=1)
        sheets = _mock_sheets([
            {**SHEET_ROW, "day": "1", "exercise": "Жим лежачи"},
            {**SHEET_ROW, "day": "1", "exercise": "Присідання"},
        ])

        line = await import_user(
            "lifter", user.id, sheets, tz_name=TZ, dry_run=False, force=False,
        )
        assert line.startswith("✅")
        sheets.get_workout_programs.assert_awaited_once_with(
            limit=0, user_name="lifter"
        )

        async with async_session_maker() as session:
            program = await WorkoutProgramRepository(session).get_program(user.id)
        assert [p["exercise"] for p in program] == ["Жим лежачи", "Присідання"]
        # get_program() formats the stored (UTC) created_at, not the
        # original local "Дата" string — 10:00 Kyiv (winter) is 08:00 UTC.
        assert program[0]["created_at"] == "07.01.2026 08:00"

    async def test_dry_run_writes_nothing(self):
        user = await _make_user("lifter", telegram_id=1)
        sheets = _mock_sheets([SHEET_ROW])

        line = await import_user(
            "lifter", user.id, sheets, tz_name=TZ, dry_run=True, force=False,
        )
        assert "dry-run" in line or "DRY" in line or "🔍" in line

        async with async_session_maker() as session:
            program = await WorkoutProgramRepository(session).get_program(user.id)
        assert program == []

    async def test_no_sheet_data_is_reported_and_writes_nothing(self):
        user = await _make_user("lifter", telegram_id=1)
        sheets = _mock_sheets([])

        line = await import_user(
            "lifter", user.id, sheets, tz_name=TZ, dry_run=False, force=False,
        )
        assert line.startswith("·")

    async def test_second_run_without_force_skips_and_does_not_duplicate(self):
        user = await _make_user("lifter", telegram_id=1)
        sheets = _mock_sheets([SHEET_ROW])

        first = await import_user(
            "lifter", user.id, sheets, tz_name=TZ, dry_run=False, force=False,
        )
        assert first.startswith("✅")

        second = await import_user(
            "lifter", user.id, sheets, tz_name=TZ, dry_run=False, force=False,
        )
        assert second.startswith("⏭️")
        # get_workout_programs must not even be called on the skip path.
        sheets.get_workout_programs.assert_awaited_once()

        async with async_session_maker() as session:
            program = await WorkoutProgramRepository(session).get_program(user.id)
        assert len(program) == 1

    async def test_force_clears_and_reimports(self):
        user = await _make_user("lifter", telegram_id=1)
        sheets = _mock_sheets([{**SHEET_ROW, "exercise": "Жим лежачи"}])
        await import_user(
            "lifter", user.id, sheets, tz_name=TZ, dry_run=False, force=False,
        )

        sheets2 = _mock_sheets([{**SHEET_ROW, "exercise": "Присідання"}])
        line = await import_user(
            "lifter", user.id, sheets2, tz_name=TZ, dry_run=False, force=True,
        )
        assert line.startswith("✅")

        async with async_session_maker() as session:
            program = await WorkoutProgramRepository(session).get_program(user.id)
        assert [p["exercise"] for p in program] == ["Присідання"]


class TestRun:
    async def test_orphan_sheet_is_reported_but_not_imported(self, capsys):
        await _make_user("lifter", telegram_id=1)
        sheets = AsyncMock()
        sheets.list_program_sheet_usernames = AsyncMock(
            return_value=["lifter", "ghost"]
        )
        sheets.get_workout_programs = AsyncMock(return_value=[SHEET_ROW])

        import scripts.import_workout_programs as mod
        original = mod.GoogleSheetsService
        mod.GoogleSheetsService = lambda: sheets
        try:
            await run(dry_run=False, only_user=None, force=False)
        finally:
            mod.GoogleSheetsService = original

        out = capsys.readouterr().out
        assert "ghost" in out
        assert "lifter" in out

        async with async_session_maker() as session:
            program = await WorkoutProgramRepository(session).get_program(
                (await UserRepository(session).get_by_telegram_id(1)).id
            )
        assert len(program) == 1

    async def test_user_filter_only_imports_that_user(self, capsys):
        await _make_user("lifter", telegram_id=1)
        await _make_user("other", telegram_id=2)
        sheets = AsyncMock()
        sheets.list_program_sheet_usernames = AsyncMock(return_value=[])
        sheets.get_workout_programs = AsyncMock(return_value=[SHEET_ROW])

        import scripts.import_workout_programs as mod
        original = mod.GoogleSheetsService
        mod.GoogleSheetsService = lambda: sheets
        try:
            await run(dry_run=False, only_user="lifter", force=False)
        finally:
            mod.GoogleSheetsService = original

        sheets.get_workout_programs.assert_awaited_once_with(
            limit=0, user_name="lifter"
        )

    async def test_unknown_user_filter_reports_and_does_nothing(self, capsys):
        await _make_user("lifter", telegram_id=1)
        sheets = AsyncMock()
        sheets.list_program_sheet_usernames = AsyncMock(return_value=[])

        import scripts.import_workout_programs as mod
        original = mod.GoogleSheetsService
        mod.GoogleSheetsService = lambda: sheets
        try:
            await run(dry_run=False, only_user="ghost", force=False)
        finally:
            mod.GoogleSheetsService = original

        sheets.get_workout_programs.assert_not_awaited()
        out = capsys.readouterr().out
        assert "ghost" in out
