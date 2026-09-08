"""Tests for GYM-14: GET /api/nutrition/statistics (src/webapp/server.py)
and DailyNutritionRepository.get_totals_by_range (src/database/repository.py).

The UTC-storage/local-day-boundary split (settings.timezone) is checked
directly against the repository with fixed datetimes, independent of
"today" (test_daily_nutrition_repository.py-style but colocated here since
GYM-14 is the only caller so far); the handler tests below use "today"
(week/month are always relative to it) only for zero-fill/aggregation
shape, not boundary precision.
"""

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

import pytest

from src.database.models import Base
from src.database.repository import (
    DailyNutritionRepository,
    ProfileRepository,
    UserRepository,
)
from src.database.session import async_session_maker, engine
from src.utils.datetime_utils import to_local_date, utcnow
from src.webapp.server import api_get_nutrition_statistics, settings
from tests.test_webapp_auth import build_init_data

# settings.timezone defaults to Europe/Kyiv (src/config.py); winter offset
# is UTC+2, so local midnight boundaries land at 22:00 the previous UTC day.


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


async def _add_record(user_id, when: datetime, **kwargs):
    async with async_session_maker() as session:
        await DailyNutritionRepository(session).create(
            user_id=user_id, date=when, **kwargs
        )
        await session.commit()


def _mock_get_request(path: str, *, telegram_id: int) -> web.Request:
    init_data = build_init_data({"id": telegram_id, "first_name": "Test"})
    return make_mocked_request(
        "GET", path, headers={"Authorization": init_data}
    )


def _utc_for_local(local_date, hour=12) -> datetime:
    """A naive-UTC datetime for `hour`:00 on `local_date` in
    settings.timezone — for anchoring test records to a specific local
    calendar day regardless of the current UTC offset.
    """
    local_dt = datetime(
        local_date.year, local_date.month, local_date.day, hour,
        tzinfo=ZoneInfo(settings.timezone),
    )
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def _today_local():
    return to_local_date(utcnow(), settings.timezone)


async def _set_profile_goals(user_id, **goals):
    async with async_session_maker() as session:
        await ProfileRepository(session).get_or_create(user_id)
        await ProfileRepository(session).update(user_id, **goals)
        await session.commit()


class TestAuthAndValidation:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "GET", "/api/nutrition/statistics", headers={"Authorization": "garbage"}
        )
        response = await api_get_nutrition_statistics(request)
        assert response.status == 401

    async def test_invalid_period_returns_400(self):
        await _make_user("eater", telegram_id=1)
        request = _mock_get_request(
            "/api/nutrition/statistics?period=all", telegram_id=1
        )
        response = await api_get_nutrition_statistics(request)
        assert response.status == 400

    async def test_unknown_caller_returns_404(self):
        request = _mock_get_request("/api/nutrition/statistics", telegram_id=999)
        response = await api_get_nutrition_statistics(request)
        assert response.status == 404


class TestZeroFill:
    async def test_week_has_seven_zeroed_days_when_empty(self):
        await _make_user("eater", telegram_id=1)
        request = _mock_get_request(
            "/api/nutrition/statistics?period=week", telegram_id=1
        )
        response = await api_get_nutrition_statistics(request)
        payload = json.loads(response.body)["data"]

        assert response.status == 200
        by_day = payload["by_day"]
        assert len(by_day) == 7
        assert all(
            row["calories"] == 0 and row["protein"] == 0 and row["fats"] == 0
            and row["carbs"] == 0 and row["water_ml"] == 0
            for row in by_day
        )
        # Monday first, consecutive calendar dates.
        dates = [datetime.fromisoformat(row["date"]).date() for row in by_day]
        assert dates[0].weekday() == 0
        assert dates == [dates[0] + timedelta(days=i) for i in range(7)]

    async def test_month_covers_every_day_of_the_current_month(self):
        await _make_user("eater", telegram_id=1)
        request = _mock_get_request(
            "/api/nutrition/statistics?period=month", telegram_id=1
        )
        response = await api_get_nutrition_statistics(request)
        payload = json.loads(response.body)["data"]

        today = _today_local()
        if today.month == 12:
            days_in_month = (
                datetime(today.year + 1, 1, 1) - datetime(today.year, 12, 1)
            ).days
        else:
            days_in_month = (
                datetime(today.year, today.month + 1, 1)
                - datetime(today.year, today.month, 1)
            ).days

        by_day = payload["by_day"]
        assert len(by_day) == days_in_month
        assert by_day[0]["date"] == today.replace(day=1).isoformat()


class TestAggregation:
    async def test_sums_multiple_records_on_the_same_local_day(self):
        user = await _make_user("eater", telegram_id=1)
        today = _today_local()
        when = _utc_for_local(today)
        await _add_record(
            user.id, when, calories=500, protein=30, fats=10, carbs=50, water_ml=250
        )
        await _add_record(
            user.id, when, calories=300, protein=20, fats=5, carbs=40, water_ml=500
        )

        request = _mock_get_request(
            "/api/nutrition/statistics?period=week", telegram_id=1
        )
        response = await api_get_nutrition_statistics(request)
        by_day = json.loads(response.body)["data"]["by_day"]

        todays_row = next(row for row in by_day if row["date"] == today.isoformat())
        assert todays_row == {
            "date": today.isoformat(),
            "calories": 800, "protein": 50, "fats": 15, "carbs": 90,
            "water_ml": 750,
        }
        # Every other day in the week stays zeroed.
        other_rows = [row for row in by_day if row["date"] != today.isoformat()]
        assert all(row["calories"] == 0 for row in other_rows)

    async def test_default_period_is_week(self):
        user = await _make_user("eater", telegram_id=1)
        await _add_record(
            user.id, _utc_for_local(_today_local()), calories=400,
        )

        request = _mock_get_request("/api/nutrition/statistics", telegram_id=1)
        response = await api_get_nutrition_statistics(request)
        by_day = json.loads(response.body)["data"]["by_day"]

        assert len(by_day) == 7


class TestRepositoryLocalDayBoundary:
    """DailyNutritionRepository.get_totals_by_range buckets by local
    calendar day, not the UTC day the timestamp happens to fall on —
    checked directly with fixed datetimes (Europe/Kyiv, winter UTC+2)
    rather than "today", since this is about the UTC/local split, not the
    handler's week/month framing.
    """

    async def test_23_30_local_stays_on_the_same_local_day(self):
        user = await _make_user("eater", telegram_id=1)
        # 2026-01-06 23:30 Kyiv (UTC+2) == 2026-01-06 21:30 UTC.
        await _add_record(
            user.id, datetime(2026, 1, 6, 21, 30), calories=111,
        )

        async with async_session_maker() as session:
            totals = await DailyNutritionRepository(session).get_totals_by_range(
                user.id,
                datetime(2026, 1, 1), datetime(2026, 1, 31),
                settings.timezone,
            )

        assert totals[date(2026, 1, 6)]["calories"] == 111
        assert date(2026, 1, 7) not in totals

    async def test_00_30_local_rolls_over_to_the_next_local_day(self):
        user = await _make_user("eater", telegram_id=1)
        # 2026-01-07 00:30 Kyiv (UTC+2) == 2026-01-06 22:30 UTC.
        await _add_record(
            user.id, datetime(2026, 1, 6, 22, 30), calories=222,
        )

        async with async_session_maker() as session:
            totals = await DailyNutritionRepository(session).get_totals_by_range(
                user.id,
                datetime(2026, 1, 1), datetime(2026, 1, 31),
                settings.timezone,
            )

        assert totals[date(2026, 1, 7)]["calories"] == 222
        assert date(2026, 1, 6) not in totals

    async def test_range_end_is_exclusive(self):
        user = await _make_user("eater", telegram_id=1)
        await _add_record(user.id, datetime(2026, 1, 10, 12, 0), calories=333)

        async with async_session_maker() as session:
            totals = await DailyNutritionRepository(session).get_totals_by_range(
                user.id,
                datetime(2026, 1, 1), datetime(2026, 1, 10, 9, 0),  # before 12:00 UTC
                settings.timezone,
            )

        assert totals == {}


class TestAvgVsGoal:
    """GYM-16: avg_vs_goal in GET /api/nutrition/statistics."""

    async def test_no_records_returns_none(self):
        await _make_user("eater", telegram_id=1)
        request = _mock_get_request(
            "/api/nutrition/statistics?period=week", telegram_id=1
        )
        response = await api_get_nutrition_statistics(request)
        payload = json.loads(response.body)["data"]

        assert payload["avg_vs_goal"] is None

    async def test_uses_default_goals_when_no_profile(self):
        user = await _make_user("eater", telegram_id=1)
        # Default calories goal is 2500 (no Profile row yet).
        await _add_record(
            user.id, _utc_for_local(_today_local()),
            calories=2000, protein=100, fats=60, carbs=200,
        )

        request = _mock_get_request(
            "/api/nutrition/statistics?period=week", telegram_id=1
        )
        response = await api_get_nutrition_statistics(request)
        avg_vs_goal = json.loads(response.body)["data"]["avg_vs_goal"]

        assert avg_vs_goal["calories_diff_pct"] == round((2000 - 2500) / 2500 * 100, 1)
        assert avg_vs_goal["protein_diff_pct"] == round((100 - 150) / 150 * 100, 1)
        assert avg_vs_goal["fats_diff_pct"] == round((60 - 80) / 80 * 100, 1)
        assert avg_vs_goal["carbs_diff_pct"] == round((200 - 250) / 250 * 100, 1)

    async def test_uses_profile_goals(self):
        user = await _make_user("eater", telegram_id=1)
        await _set_profile_goals(
            user.id, daily_calories=2000, daily_protein=200,
            daily_fats=70, daily_carbs=180,
        )
        await _add_record(
            user.id, _utc_for_local(_today_local()),
            calories=2200, protein=180, fats=70, carbs=198,
        )

        request = _mock_get_request(
            "/api/nutrition/statistics?period=week", telegram_id=1
        )
        response = await api_get_nutrition_statistics(request)
        avg_vs_goal = json.loads(response.body)["data"]["avg_vs_goal"]

        assert avg_vs_goal["calories_diff_pct"] == 10.0    # +200/2000
        assert avg_vs_goal["protein_diff_pct"] == -10.0    # -20/200
        assert avg_vs_goal["fats_diff_pct"] == 0.0
        assert avg_vs_goal["carbs_diff_pct"] == 10.0        # +18/180

    async def test_days_without_records_are_excluded_from_the_average(self):
        user = await _make_user("eater", telegram_id=1)
        await _set_profile_goals(user.id, daily_calories=2000)
        # Only today has a record; the rest of the week is zero-filled in
        # by_day but must NOT drag the average toward zero.
        await _add_record(
            user.id, _utc_for_local(_today_local()), calories=2000,
        )

        request = _mock_get_request(
            "/api/nutrition/statistics?period=week", telegram_id=1
        )
        response = await api_get_nutrition_statistics(request)
        avg_vs_goal = json.loads(response.body)["data"]["avg_vs_goal"]

        # If zero-days were included, avg would be far below goal.
        assert avg_vs_goal["calories_diff_pct"] == 0.0

    async def test_goal_of_zero_returns_none_for_that_metric(self):
        user = await _make_user("eater", telegram_id=1)
        await _set_profile_goals(user.id, daily_carbs=0)
        await _add_record(user.id, _utc_for_local(_today_local()), carbs=50)

        request = _mock_get_request(
            "/api/nutrition/statistics?period=week", telegram_id=1
        )
        response = await api_get_nutrition_statistics(request)
        avg_vs_goal = json.loads(response.body)["data"]["avg_vs_goal"]

        assert avg_vs_goal["carbs_diff_pct"] is None
