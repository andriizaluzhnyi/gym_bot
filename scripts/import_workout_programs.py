"""GYM-29: one-time import of workout programs from Google Sheets into the
DB-backed schema (GYM-27/28).

Run this once, after upgrading to a version that includes GYM-28, to bring
existing clients' programs (previously only in the "Програми (<username>)"
Google Sheets tabs) into the ``workout_program_exercises`` table — from
that point on the DB is the primary store and Sheets is only an optional
mirror, so nothing further reads this data back out of Sheets.

Usage:
    python scripts/import_workout_programs.py [--dry-run] [--user <username>] [--force]

Options:
    --dry-run          Don't write anything; just report what would happen.
    --user <username>  Only import this one user's sheet (still validated
                        against the DB — errors out if no such user with
                        a username exists).
    --force            Delete a user's existing DB program rows and
                        reimport from scratch, instead of skipping them.

Idempotency: a user who already has at least one program row in the DB is
skipped (with a log message) unless ``--force`` is passed. Running the
script twice without ``--force`` is therefore safe and does not duplicate
rows.
"""

import argparse
import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Add project root to path, matching the other one-off scripts in this dir
# (scripts/clean_daily_nutrition_data.py, scripts/check_daily_nutrition.py).
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config import get_settings  # noqa: E402
from src.database.repository import (  # noqa: E402
    UserRepository,
    WorkoutProgramRepository,
)
from src.database.session import async_session_maker  # noqa: E402
from src.services.google_sheets import GoogleSheetsService  # noqa: E402
from src.utils.datetime_utils import utcnow  # noqa: E402

DATE_FORMAT = "%d.%m.%Y %H:%M"


def parse_program_row(row: dict, *, tz_name: str, now: datetime | None = None) -> dict:
    """Pure function: one raw Sheets program row (``day``, ``muscle_group``,
    ``exercise``, ``sets_reps``, ``comment``, ``created_at`` — all strings,
    the shape ``GoogleSheetsService.get_workout_programs`` returns) into
    one item ready for ``WorkoutProgramRepository.add_exercises``.

    The output's ``created_at_utc`` is parsed from the row's "Дата" column
    (``%d.%m.%Y %H:%M``, written by ``add_workout_program`` using local
    server time — see ``src/services/google_sheets.py``), interpreted in
    ``tz_name`` and converted to naive-UTC. Falls back to ``now`` (defaults
    to :func:`utcnow`) when the column is missing or doesn't parse, per
    GYM-29's AC. (Named ``created_at_utc``, not ``created_at``, because
    ``add_exercises`` deliberately keeps that key free for the FSM's own
    Sheets-mirror string — see its docstring.)
    """
    item = {
        "exercise": row.get("exercise", ""),
        "muscle_group": row.get("muscle_group", ""),
        "sets_reps": row.get("sets_reps", ""),
        "comment": row.get("comment") or "",
    }
    created_at_str = (row.get("created_at") or "").strip()
    try:
        naive_local = datetime.strptime(created_at_str, DATE_FORMAT)
        aware_local = naive_local.replace(tzinfo=ZoneInfo(tz_name))
        item["created_at_utc"] = aware_local.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        item["created_at_utc"] = now if now is not None else utcnow()
    return item


def group_rows_by_day(rows: list[dict]) -> dict[int, list[dict]]:
    """Group raw Sheets rows by ``day`` (parsed as ``int``, defaulting to
    ``1`` for anything blank/unparseable), preserving each row's original
    order within its day. That per-day order is what becomes ``position``
    when the group is later passed to ``add_exercises`` — GYM-29's AC:
    "зберігаючи порядок рядків як position".
    """
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        try:
            day = int(str(row.get("day", "1")).strip() or "1")
        except ValueError:
            day = 1
        grouped.setdefault(day, []).append(row)
    return grouped


async def import_user(
    username: str,
    user_id: uuid.UUID,
    sheets: GoogleSheetsService,
    *,
    tz_name: str,
    dry_run: bool,
    force: bool,
) -> str:
    """Import one user's program sheet into the DB. Returns a one-line
    status message for the final report.
    """
    async with async_session_maker() as session:
        repo = WorkoutProgramRepository(session)
        existing = await repo.get_program(user_id)

        if existing and not force:
            return (
                f"⏭️  {username}: у БД вже є {len(existing)} рядків програми — "
                f"пропущено (--force для перезапису)"
            )

        raw_rows = await sheets.get_workout_programs(limit=0, user_name=username)
        if not raw_rows:
            return f"·  {username}: у Google Sheets немає рядків програми"

        rows_by_day = group_rows_by_day(raw_rows)
        items_by_day = {
            day: [parse_program_row(row, tz_name=tz_name) for row in day_rows]
            for day, day_rows in rows_by_day.items()
        }
        total = sum(len(items) for items in items_by_day.values())

        if dry_run:
            return (
                f"🔍 {username}: буде імпортовано {total} рядків "
                f"у {len(items_by_day)} день(днів) (--dry-run, нічого не записано)"
            )

        if existing and force:
            deleted = await repo.delete_all_for_user(user_id)
            print(f"   🗑️  {username}: видалено {deleted} існуючих рядків (--force)")

        for day in sorted(items_by_day):
            await repo.add_exercises(user_id, day, items_by_day[day])
        await session.commit()

        return f"✅ {username}: імпортовано {total} рядків у {len(items_by_day)} день(днів)"


async def run(*, dry_run: bool, only_user: str | None, force: bool) -> None:
    settings = get_settings()
    sheets = GoogleSheetsService()

    async with async_session_maker() as session:
        db_users = await UserRepository(session).get_all_with_username()

    sheet_usernames = set(await sheets.list_program_sheet_usernames())
    db_usernames = {u.username for u in db_users if u.username}

    if only_user is not None:
        db_users = [u for u in db_users if u.username == only_user]
        if not db_users:
            print(
                f"❌ Активного користувача з username={only_user!r} не знайдено — "
                f"нічого імпортувати."
            )
            return

    print(f"Користувачів з username у БД: {len(db_usernames)}")
    print(f"Аркушів програм у Google Sheets: {len(sheet_usernames)}")

    orphan_sheets = sorted(sheet_usernames - db_usernames)
    if orphan_sheets:
        print(
            "\n⚠️  Аркуші без відповідного користувача в БД (не імпортуються):"
        )
        for name in orphan_sheets:
            print(f"   - {name}")

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Імпорт програм{f' для {only_user}' if only_user else ''}...")
    report_lines = []
    for user in db_users:
        assert user.username is not None  # guaranteed by get_all_with_username
        line = await import_user(
            user.username, user.id, sheets,
            tz_name=settings.timezone, dry_run=dry_run, force=force,
        )
        print(line)
        report_lines.append(line)

    imported = sum(1 for line in report_lines if line.startswith("✅"))
    skipped = sum(1 for line in report_lines if line.startswith("⏭️"))
    empty = sum(1 for line in report_lines if line.startswith("·"))
    print(
        f"\nГотово: імпортовано {imported}, пропущено (вже в БД) {skipped}, "
        f"без даних у Sheets {empty}, без користувача в БД {len(orphan_sheets)}."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Одноразовий імпорт програм тренувань із Google Sheets у БД (GYM-29)."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Показати, що буде імпортовано, нічого не записуючи в БД.",
    )
    parser.add_argument(
        "--user", default=None, metavar="USERNAME",
        help="Імпортувати лише цього користувача (за username).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Видалити наявні в БД рядки програми користувача й імпортувати заново.",
    )
    args = parser.parse_args()

    asyncio.run(run(dry_run=args.dry_run, only_user=args.user, force=args.force))


if __name__ == "__main__":
    main()
