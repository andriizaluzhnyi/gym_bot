"""Tests for GYM-12: GET /api/statistics/streak (src/webapp/server.py).

calculate_streak() itself is unit-tested against plain dates in
tests/test_streak.py; these tests cover the handler's DB wiring
(auth, owner resolution, session -> local-date conversion) instead.
"""

import json
from datetime import datetime, timedelta

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.database.models import Base
from src.database.repository import UserRepository, WorkoutSessionRepository
from src.database.session import async_session_maker, engine
from src.utils.datetime_utils import to_local_date, utcnow
from src.webapp.server import api_get_streak, settings
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


async def _add_completed_session(user_id, performed_at: datetime, **kwargs):
    async with async_session_maker() as session:
        await WorkoutSessionRepository(session).create_session_with_sets(
            user_id=user_id, performed_at=performed_at, sets=[{
                "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                "set_number": 1, "weight": 60.0, "reps": 10,
            }], **kwargs,
        )
        await session.commit()


def _mock_get_request(path: str, *, telegram_id: int) -> web.Request:
    init_data = build_init_data({"id": telegram_id, "first_name": "Test"})
    return make_mocked_request(
        "GET", path, headers={"Authorization": init_data}
    )


def _weeks_ago(n: int) -> datetime:
    """A performed_at timestamp `n` weeks before "now", in the middle of
    that ISO week — safely away from a Sunday/Monday boundary so the
    calling test doesn't have to reason about it.
    """
    today_local = to_local_date(utcnow(), settings.timezone)
    monday_this_week = today_local - timedelta(days=today_local.weekday())
    target_date = monday_this_week - timedelta(weeks=n)
    return datetime(target_date.year, target_date.month, target_date.day, 12, 0)


class TestAuthAndValidation:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "GET", "/api/statistics/streak", headers={"Authorization": "garbage"}
        )
        response = await api_get_streak(request)
        assert response.status == 401

    async def test_unknown_caller_returns_404(self):
        request = _mock_get_request("/api/statistics/streak", telegram_id=999)
        response = await api_get_streak(request)
        assert response.status == 404


class TestStreak:
    async def test_no_sessions_returns_zero_streaks(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request("/api/statistics/streak", telegram_id=1)
        response = await api_get_streak(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload == {
            "success": True,
            "data": {"current_streak": 0, "longest_streak": 0, "unit": "week"},
        }

    async def test_consecutive_weeks_build_a_streak(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(user.id, _weeks_ago(2))
        await _add_completed_session(user.id, _weeks_ago(1))
        await _add_completed_session(user.id, _weeks_ago(0))

        request = _mock_get_request("/api/statistics/streak", telegram_id=1)
        response = await api_get_streak(request)
        data = json.loads(response.body)["data"]

        assert data["current_streak"] == 3
        assert data["longest_streak"] == 3
        assert data["unit"] == "week"

    async def test_current_incomplete_week_does_not_break_the_streak(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(user.id, _weeks_ago(2))
        await _add_completed_session(user.id, _weeks_ago(1))
        # Nothing logged this week yet.

        request = _mock_get_request("/api/statistics/streak", telegram_id=1)
        response = await api_get_streak(request)
        data = json.loads(response.body)["data"]

        assert data["current_streak"] == 2

    async def test_draft_session_is_excluded(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            await WorkoutSessionRepository(session).start_draft_session(user.id)
            await session.commit()

        request = _mock_get_request("/api/statistics/streak", telegram_id=1)
        response = await api_get_streak(request)
        data = json.loads(response.body)["data"]

        assert data == {"current_streak": 0, "longest_streak": 0, "unit": "week"}

    async def test_user_param_overrides_caller(self):
        owner = await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)
        await _add_completed_session(owner.id, _weeks_ago(0))

        request = _mock_get_request(
            "/api/statistics/streak?user=lifter", telegram_id=999
        )
        response = await api_get_streak(request)
        data = json.loads(response.body)["data"]

        assert data["current_streak"] == 1
