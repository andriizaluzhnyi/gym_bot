"""Tests for GYM-40: GET /api/statistics/today (src/webapp/server.py)."""

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.database.models import Base
from src.database.repository import UserRepository, WorkoutSessionRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import api_get_today_workout, settings
from src.utils.datetime_utils import to_local_date, utcnow
from tests.test_webapp_auth import build_init_data

# settings.timezone defaults to Europe/Kyiv (src/config.py); winter offset
# is UTC+2, so local midnight lands at 22:00 the previous UTC day.


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


async def _add_completed_session(user_id, performed_at: datetime, sets: list[dict], **kwargs):
    async with async_session_maker() as session:
        workout_session = await WorkoutSessionRepository(session).create_session_with_sets(
            user_id=user_id, performed_at=performed_at, sets=sets, **kwargs
        )
        await session.commit()
        return workout_session.id


def _mock_get_request(path: str, *, telegram_id: int) -> web.Request:
    init_data = build_init_data({"id": telegram_id, "first_name": "Test"})
    return make_mocked_request("GET", path, headers={"Authorization": init_data})


def _utc_for_local(local_date, hour=12) -> datetime:
    local_dt = datetime(
        local_date.year, local_date.month, local_date.day, hour,
        tzinfo=ZoneInfo(settings.timezone),
    )
    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)


def _today_local():
    return to_local_date(utcnow(), settings.timezone)


CHEST_SET = {
    "exercise_name": "Жим лежачи",
    "muscle_group": "Груди",
    "set_number": 1,
    "weight": 60.0,
    "reps": 10,
}
LEGS_SET = {
    "exercise_name": "Присідання",
    "muscle_group": "Ноги",
    "set_number": 1,
    "weight": 100.0,
    "reps": 5,
}


class TestAuthAndValidation:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "GET", "/api/statistics/today", headers={"Authorization": "garbage"}
        )
        response = await api_get_today_workout(request)
        assert response.status == 401

    async def test_unknown_caller_returns_404(self):
        request = _mock_get_request("/api/statistics/today", telegram_id=999)
        response = await api_get_today_workout(request)
        assert response.status == 404


class TestNoWorkoutToday:
    async def test_returns_null_with_no_sessions_at_all(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request("/api/statistics/today", telegram_id=1)
        response = await api_get_today_workout(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload == {"success": True, "data": None}

    async def test_yesterdays_session_does_not_count(self):
        user = await _make_user("lifter", telegram_id=1)
        yesterday = _utc_for_local(_today_local()) - timedelta(days=1)
        await _add_completed_session(user.id, yesterday, sets=[CHEST_SET])

        request = _mock_get_request("/api/statistics/today", telegram_id=1)
        response = await api_get_today_workout(request)
        payload = json.loads(response.body)

        assert payload["data"] is None

    async def test_draft_session_today_does_not_count(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            await WorkoutSessionRepository(session).start_draft_session(user.id)
            await session.commit()

        request = _mock_get_request("/api/statistics/today", telegram_id=1)
        response = await api_get_today_workout(request)
        payload = json.loads(response.body)

        assert payload["data"] is None


class TestWorkoutToday:
    async def test_returns_the_session_summary(self):
        user = await _make_user("lifter", telegram_id=1)
        session_id = await _add_completed_session(
            user.id, _utc_for_local(_today_local()),
            sets=[CHEST_SET, {**CHEST_SET, "set_number": 2}],
            muscle_group="Груди", duration_seconds=1800,
        )

        request = _mock_get_request("/api/statistics/today", telegram_id=1)
        response = await api_get_today_workout(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload["data"] == {
            "session_id": session_id,
            "date": _today_local().isoformat(),
            "muscle_group": "Груди",
            "exercises_count": 1,
            "sets_count": 2,
            "total_volume": 1200.0,  # 60*10 * 2 sets
            "duration_minutes": 30.0,
        }

    async def test_a_1_am_local_session_counts_as_today(self):
        """The same UTC-storage/local-day-boundary split as GYM-21/GYM-40's
        own /api/nutrition/daily: a session just after local midnight must
        not be read as "yesterday"."""
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id, _utc_for_local(_today_local(), hour=1), sets=[CHEST_SET],
        )

        request = _mock_get_request("/api/statistics/today", telegram_id=1)
        response = await api_get_today_workout(request)
        payload = json.loads(response.body)

        assert payload["data"] is not None

    async def test_two_sessions_today_returns_the_most_recent(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id, _utc_for_local(_today_local(), hour=8),
            sets=[LEGS_SET], muscle_group="Ноги",
        )
        newest_id = await _add_completed_session(
            user.id, _utc_for_local(_today_local(), hour=18),
            sets=[CHEST_SET], muscle_group="Груди",
        )

        request = _mock_get_request("/api/statistics/today", telegram_id=1)
        response = await api_get_today_workout(request)
        payload = json.loads(response.body)

        assert payload["data"]["session_id"] == newest_id
        assert payload["data"]["muscle_group"] == "Груди"


class TestTrainerViewsClient:
    async def test_user_param_overrides_caller(self, monkeypatch):
        # GYM-28: ?user= for someone else now requires the caller to be an
        # admin — a plain "trainer" account no longer suffices on its own.
        monkeypatch.setattr(settings, "admin_user_id", 999)
        owner = await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)
        await _add_completed_session(
            owner.id, _utc_for_local(_today_local()), sets=[CHEST_SET],
        )

        request = _mock_get_request(
            "/api/statistics/today?user=lifter", telegram_id=999
        )
        response = await api_get_today_workout(request)
        payload = json.loads(response.body)

        assert payload["data"] is not None
