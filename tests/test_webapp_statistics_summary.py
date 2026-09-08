"""Tests for GYM-6: GET /api/statistics/summary (src/webapp/server.py)."""

import json
from datetime import datetime

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.database.models import Base
from src.database.repository import UserRepository, WorkoutSessionRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import api_get_statistics_summary, settings
from tests.test_webapp_auth import build_init_data

import pytest

# settings.timezone defaults to Europe/Kyiv (src/config.py).


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


async def _add_completed_session(
    user_id, performed_at: datetime, sets: list[dict], **kwargs
):
    async with async_session_maker() as session:
        await WorkoutSessionRepository(session).create_session_with_sets(
            user_id=user_id, performed_at=performed_at, sets=sets, **kwargs
        )
        await session.commit()


def _mock_get_request(path: str, *, telegram_id: int) -> web.Request:
    init_data = build_init_data({"id": telegram_id, "first_name": "Test"})
    return make_mocked_request(
        "GET", path, headers={"Authorization": init_data}
    )


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
            "GET", "/api/statistics/summary", headers={"Authorization": "garbage"}
        )
        response = await api_get_statistics_summary(request)
        assert response.status == 401

    async def test_invalid_period_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request(
            "/api/statistics/summary?period=year", telegram_id=1
        )
        response = await api_get_statistics_summary(request)
        assert response.status == 400

    async def test_unknown_caller_returns_404(self):
        request = _mock_get_request("/api/statistics/summary", telegram_id=999)
        response = await api_get_statistics_summary(request)
        assert response.status == 404


class TestEmptyPeriod:
    async def test_no_sessions_returns_zeroed_response(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request(
            "/api/statistics/summary?period=all", telegram_id=1
        )
        response = await api_get_statistics_summary(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload == {
            "success": True,
            "data": {
                "workouts_count": 0,
                "avg_duration_minutes": 0,
                "total_volume": 0.0,
                "most_trained_muscle": None,
            },
        }


class TestAggregation:
    async def test_counts_sessions_and_averages_duration(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id, datetime(2026, 1, 6, 8, 0),
            sets=[CHEST_SET], duration_seconds=1800,
        )
        await _add_completed_session(
            user.id, datetime(2026, 1, 7, 8, 0),
            sets=[LEGS_SET], duration_seconds=2400,
        )

        request = _mock_get_request(
            "/api/statistics/summary?period=all", telegram_id=1
        )
        response = await api_get_statistics_summary(request)
        payload = json.loads(response.body)["data"]

        assert response.status == 200
        assert payload["workouts_count"] == 2
        assert payload["avg_duration_minutes"] == 35.0  # (1800+2400)/2/60
        assert payload["total_volume"] == 1100.0  # 60*10 + 100*5

    async def test_most_trained_muscle_is_highest_volume(self):
        user = await _make_user("lifter", telegram_id=1)
        # Legs: 500 volume. Chest: 600 volume (two sets). Chest should win.
        await _add_completed_session(
            user.id, datetime(2026, 1, 6, 8, 0),
            sets=[CHEST_SET, {**CHEST_SET, "set_number": 2}],
        )
        await _add_completed_session(
            user.id, datetime(2026, 1, 7, 8, 0),
            sets=[LEGS_SET],
        )

        request = _mock_get_request(
            "/api/statistics/summary?period=all", telegram_id=1
        )
        response = await api_get_statistics_summary(request)
        payload = json.loads(response.body)["data"]

        assert payload["most_trained_muscle"] == "Груди"

    async def test_sessions_without_duration_are_excluded_from_average(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id, datetime(2026, 1, 6, 8, 0),
            sets=[CHEST_SET], duration_seconds=None,
        )
        await _add_completed_session(
            user.id, datetime(2026, 1, 7, 8, 0),
            sets=[LEGS_SET], duration_seconds=1200,
        )

        request = _mock_get_request(
            "/api/statistics/summary?period=all", telegram_id=1
        )
        response = await api_get_statistics_summary(request)
        payload = json.loads(response.body)["data"]

        assert payload["workouts_count"] == 2
        assert payload["avg_duration_minutes"] == 20.0  # only the 1200s session

    async def test_draft_session_is_excluded(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            await WorkoutSessionRepository(session).start_draft_session(user.id)
            await session.commit()

        request = _mock_get_request(
            "/api/statistics/summary?period=all", telegram_id=1
        )
        response = await api_get_statistics_summary(request)
        payload = json.loads(response.body)["data"]

        assert payload["workouts_count"] == 0

    async def test_session_outside_period_is_excluded(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id, datetime(2020, 1, 1, 8, 0), sets=[CHEST_SET],
        )

        request = _mock_get_request(
            "/api/statistics/summary?period=week", telegram_id=1
        )
        response = await api_get_statistics_summary(request)
        payload = json.loads(response.body)["data"]

        assert payload["workouts_count"] == 0


class TestTrainerViewsClient:
    async def test_user_param_overrides_caller(self, monkeypatch):
        # GYM-28: ?user= for someone else now requires the caller to be an
        # admin — a plain "trainer" account no longer suffices on its own.
        monkeypatch.setattr(settings, "admin_user_id", 999)
        owner = await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)
        await _add_completed_session(
            owner.id, datetime(2026, 1, 6, 8, 0),
            sets=[CHEST_SET], duration_seconds=1800,
        )

        request = _mock_get_request(
            "/api/statistics/summary?period=all&user=lifter", telegram_id=999
        )
        response = await api_get_statistics_summary(request)
        payload = json.loads(response.body)["data"]

        assert payload["workouts_count"] == 1
