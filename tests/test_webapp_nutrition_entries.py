"""Tests for GYM-21: explicit `DailyNutrition.entry_type`/`meal_name`,
local-calendar-day boundaries for "today", and `DELETE /api/nutrition/meal/{id}`
(src/webapp/server.py, src/database/repository.py).
"""

import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.database.models import Base, DailyNutrition, NutritionEntryType
from src.database.repository import DailyNutritionRepository, UserRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import (
    api_add_meal,
    api_delete_meal,
    api_get_daily_nutrition,
    api_get_today_meals,
    api_save_daily_nutrition,
    settings,
)
from tests.test_webapp_auth import build_init_data

# settings.timezone defaults to Europe/Kyiv (src/config.py); winter offset
# is UTC+2, so local midnight lands at 22:00 the previous UTC day.


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _make_user(telegram_id: int):
    async with async_session_maker() as session:
        user, _ = await UserRepository(session).get_or_create(
            telegram_id=telegram_id, first_name="Test"
        )
        await session.commit()
        return user


async def _add_entry(user_id, when: datetime, entry_type: str, **kwargs):
    async with async_session_maker() as session:
        record = await DailyNutritionRepository(session).create(
            user_id=user_id, date=when, entry_type=entry_type, **kwargs
        )
        await session.commit()
        return record.id


def _utc_for_local(local_date, hour=12) -> datetime:
    local_dt = datetime(
        local_date.year, local_date.month, local_date.day, hour,
        tzinfo=ZoneInfo(settings.timezone),
    )
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def _mock_request(
    method: str, path: str, *, telegram_id: int,
    body: dict | None = None, match_info: dict | None = None,
) -> web.Request:
    init_data = build_init_data({"id": telegram_id, "first_name": "Test"})
    request = make_mocked_request(
        method, path,
        headers={"Authorization": init_data},
        match_info=match_info or {},
    )
    if body is not None:
        async def fake_json():
            return body
        request.json = fake_json  # type: ignore[method-assign, assignment]
    return request


class TestApiSaveDailyNutritionSetsWaterEntryType:
    async def test_water_entry_is_excluded_from_meals_list(self):
        user = await _make_user(1)
        request = _mock_request(
            "POST", "/api/nutrition/daily", telegram_id=1,
            body={"water_ml": 250},
        )

        response = await api_save_daily_nutrition(request)
        assert response.status == 200

        async with async_session_maker() as session:
            meals = await DailyNutritionRepository(session).get_meals_for_local_day(
                user.id, settings.timezone
            )
        assert meals == []


class TestApiAddMealPersistsNameAndType:
    async def test_meal_name_is_persisted_and_returned(self):
        await _make_user(1)
        request = _mock_request(
            "POST", "/api/nutrition/meal", telegram_id=1,
            body={
                "meal_name": "Куряча грудка з рисом",
                "calories": 450, "protein": 40, "fats": 10, "carbs": 50,
            },
        )

        response = await api_add_meal(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload["data"]["meal_name"] == "Куряча грудка з рисом"

        async with async_session_maker() as session:
            record = await session.get(DailyNutrition, payload["data"]["id"])
        assert record.entry_type == NutritionEntryType.MEAL.value
        assert record.meal_name == "Куряча грудка з рисом"

    async def test_meal_appears_in_meals_list_with_name(self):
        await _make_user(1)
        request = _mock_request(
            "POST", "/api/nutrition/meal", telegram_id=1,
            body={"meal_name": "Салат", "calories": 100, "protein": 5, "fats": 5, "carbs": 10},
        )
        await api_add_meal(request)

        meals_request = _mock_request("GET", "/api/nutrition/meals", telegram_id=1)
        response = await api_get_today_meals(meals_request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert len(payload["data"]) == 1
        assert payload["data"][0]["meal_name"] == "Салат"

    async def test_meals_list_excludes_water_entries(self):
        await _make_user(1)
        water_request = _mock_request(
            "POST", "/api/nutrition/daily", telegram_id=1, body={"water_ml": 200},
        )
        await api_save_daily_nutrition(water_request)
        meal_request = _mock_request(
            "POST", "/api/nutrition/meal", telegram_id=1,
            body={"meal_name": "Омлет", "calories": 200, "protein": 15, "fats": 15, "carbs": 2},
        )
        await api_add_meal(meal_request)

        meals_request = _mock_request("GET", "/api/nutrition/meals", telegram_id=1)
        response = await api_get_today_meals(meals_request)
        payload = json.loads(response.body)

        assert len(payload["data"]) == 1
        assert payload["data"][0]["meal_name"] == "Омлет"


class TestLocalDayBoundaryDirectOnRepository:
    """Fixed-datetime checks against the repository (not "today"), same
    approach as GYM-14's TestRepositoryLocalDayBoundary in
    test_webapp_nutrition_statistics.py — this is about the UTC/local split,
    not about "now".
    """

    async def test_01_00_local_counts_as_that_local_day_not_the_prior_utc_day(self):
        user = await _make_user(1)
        # 2026-01-07 01:00 Kyiv (winter, UTC+2) == 2026-01-06 23:00 UTC —
        # a naive UTC-midnight boundary would have put this in Jan 6.
        when = datetime(2026, 1, 6, 23, 0)
        await _add_entry(
            user.id, when, NutritionEntryType.WATER.value, water_ml=300,
        )

        async with async_session_maker() as session:
            totals = await DailyNutritionRepository(session).get_today_total(
                user.id, settings.timezone,
                now_utc=datetime(2026, 1, 7, 5, 0),  # 07:00 Kyiv, same local day
            )
        assert totals["water_ml"] == 300

    async def test_23_30_utc_previous_day_is_excluded_from_todays_total(self):
        user = await _make_user(1)
        # 2026-01-05 23:30 Kyiv (winter, UTC+2) == 2026-01-05 21:30 UTC —
        # the local day *before* the one we ask about.
        when = datetime(2026, 1, 5, 21, 30)
        await _add_entry(
            user.id, when, NutritionEntryType.WATER.value, water_ml=999,
        )

        async with async_session_maker() as session:
            totals = await DailyNutritionRepository(session).get_today_total(
                user.id, settings.timezone,
                now_utc=datetime(2026, 1, 7, 5, 0),
            )
        assert totals["water_ml"] == 0

    async def test_meals_for_local_day_respects_the_same_boundary(self):
        user = await _make_user(1)
        when = datetime(2026, 1, 6, 23, 0)  # 01:00 Kyiv on Jan 7
        await _add_entry(
            user.id, when, NutritionEntryType.MEAL.value,
            meal_name="Нічний перекус", calories=150,
        )

        async with async_session_maker() as session:
            meals = await DailyNutritionRepository(session).get_meals_for_local_day(
                user.id, settings.timezone,
                now_utc=datetime(2026, 1, 7, 5, 0),
            )
        assert len(meals) == 1
        assert meals[0].meal_name == "Нічний перекус"


class TestApiDeleteMeal:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "DELETE", "/api/nutrition/meal/1",
            headers={"Authorization": "garbage"}, match_info={"id": "1"},
        )
        response = await api_delete_meal(request)
        assert response.status == 401

    async def test_non_numeric_id_returns_400(self):
        await _make_user(1)
        request = _mock_request(
            "DELETE", "/api/nutrition/meal/abc", telegram_id=1,
            match_info={"id": "abc"},
        )
        response = await api_delete_meal(request)
        assert response.status == 400

    async def test_unknown_id_returns_404(self):
        await _make_user(1)
        request = _mock_request(
            "DELETE", "/api/nutrition/meal/999999", telegram_id=1,
            match_info={"id": "999999"},
        )
        response = await api_delete_meal(request)
        assert response.status == 404

    async def test_deletes_own_meal(self):
        user = await _make_user(1)
        entry_id = await _add_entry(
            user.id, _utc_for_local(date(2026, 1, 7)),
            NutritionEntryType.MEAL.value, meal_name="Помилка", calories=100,
        )

        request = _mock_request(
            "DELETE", f"/api/nutrition/meal/{entry_id}", telegram_id=1,
            match_info={"id": str(entry_id)},
        )
        response = await api_delete_meal(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload == {"success": True}

        async with async_session_maker() as session:
            record = await session.get(DailyNutrition, entry_id)
        assert record is None

    async def test_deletes_own_water_entry(self):
        """DELETE also works for water entries (e.g. an "undo" action),
        not just meals — the endpoint doesn't filter by entry_type.
        """
        user = await _make_user(1)
        entry_id = await _add_entry(
            user.id, _utc_for_local(date(2026, 1, 7)),
            NutritionEntryType.WATER.value, water_ml=250,
        )

        request = _mock_request(
            "DELETE", f"/api/nutrition/meal/{entry_id}", telegram_id=1,
            match_info={"id": str(entry_id)},
        )
        response = await api_delete_meal(request)
        assert response.status == 200

    async def test_cannot_delete_someone_elses_entry(self):
        owner = await _make_user(1)
        await _make_user(2)
        entry_id = await _add_entry(
            owner.id, _utc_for_local(date(2026, 1, 7)),
            NutritionEntryType.MEAL.value, meal_name="Чужий обід", calories=300,
        )

        request = _mock_request(
            "DELETE", f"/api/nutrition/meal/{entry_id}", telegram_id=2,
            match_info={"id": str(entry_id)},
        )
        response = await api_delete_meal(request)

        assert response.status == 404
        async with async_session_maker() as session:
            record = await session.get(DailyNutrition, entry_id)
        assert record is not None


class TestApiGetDailyNutritionUsesLocalDay:
    async def test_totals_reflect_local_calendar_day(self):
        user = await _make_user(1)
        # A record made 01:00 local time still counts toward "today" even
        # though it's technically the previous UTC calendar day.
        now_local = datetime.now(ZoneInfo(settings.timezone))
        early_local = now_local.replace(hour=1, minute=0, second=0, microsecond=0)
        when_utc = early_local.astimezone(timezone.utc).replace(tzinfo=None)
        await _add_entry(
            user.id, when_utc, NutritionEntryType.WATER.value, water_ml=400,
        )

        request = _mock_request("GET", "/api/nutrition/daily", telegram_id=1)
        response = await api_get_daily_nutrition(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload["data"]["water_ml"] == 400
