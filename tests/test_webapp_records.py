"""Tests for GYM-8: GET /api/statistics/records (src/webapp/server.py)."""

import json
from datetime import datetime

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.database.models import Base
from src.database.repository import UserRepository, WorkoutSessionRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import api_get_records, settings
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


class TestAuthAndValidation:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "GET", "/api/statistics/records", headers={"Authorization": "garbage"}
        )
        response = await api_get_records(request)
        assert response.status == 401

    async def test_unknown_caller_returns_404(self):
        request = _mock_get_request("/api/statistics/records", telegram_id=999)
        response = await api_get_records(request)
        assert response.status == 404


class TestEmpty:
    async def test_no_sets_returns_empty_list(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request("/api/statistics/records", telegram_id=1)
        response = await api_get_records(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload == {"success": True, "data": []}


class TestRecords:
    async def test_single_exercise_record_shape(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id, datetime(2026, 1, 6, 8, 0),
            sets=[{
                "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                "set_number": 1, "weight": 80.0, "reps": 5,
            }],
        )

        request = _mock_get_request("/api/statistics/records", telegram_id=1)
        response = await api_get_records(request)
        payload = json.loads(response.body)["data"]

        assert response.status == 200
        assert len(payload) == 1
        record = payload[0]
        assert record["exercise"] == "Жим лежачи"
        assert record["muscle_group"] == "Груди"
        assert record["max_weight"] == {
            "weight": 80.0, "reps": 5, "achieved_at": "2026-01-06",
        }
        assert record["max_reps"] == {
            "weight": 80.0, "reps": 5, "achieved_at": "2026-01-06",
        }
        assert record["estimated_1rm"]["estimated_1rm"] == round(
            80.0 * (1 + 5 / 30), 1
        )
        assert record["achieved_at"] == "2026-01-06"

    async def test_top_level_achieved_at_is_the_most_recent_of_the_three(self):
        user = await _make_user("lifter", telegram_id=1)
        # Heaviest weight set later than the best-1RM/most-reps set.
        await _add_completed_session(
            user.id, datetime(2026, 1, 1, 8, 0),
            sets=[{
                "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                "set_number": 1, "weight": 60.0, "reps": 15,
            }],
        )
        await _add_completed_session(
            user.id, datetime(2026, 1, 20, 8, 0),
            sets=[{
                "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                "set_number": 1, "weight": 100.0, "reps": 1,
            }],
        )

        request = _mock_get_request("/api/statistics/records", telegram_id=1)
        response = await api_get_records(request)
        record = json.loads(response.body)["data"][0]

        assert record["max_weight"]["achieved_at"] == "2026-01-20"
        assert record["max_reps"]["achieved_at"] == "2026-01-01"
        assert record["achieved_at"] == "2026-01-20"

    async def test_multiple_exercises_sorted_by_muscle_group_then_name(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id, datetime(2026, 1, 6, 8, 0),
            sets=[
                {
                    "exercise_name": "Присідання", "muscle_group": "Ноги",
                    "set_number": 1, "weight": 100.0, "reps": 5,
                },
                {
                    "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                    "set_number": 1, "weight": 60.0, "reps": 10,
                },
                {
                    "exercise_name": "Тяга блоку", "muscle_group": "Груди",
                    "set_number": 1, "weight": 50.0, "reps": 10,
                },
            ],
        )

        request = _mock_get_request("/api/statistics/records", telegram_id=1)
        response = await api_get_records(request)
        payload = json.loads(response.body)["data"]

        exercises = [(r["muscle_group"], r["exercise"]) for r in payload]
        assert exercises == [
            ("Груди", "Жим лежачи"),
            ("Груди", "Тяга блоку"),
            ("Ноги", "Присідання"),
        ]

    async def test_draft_session_is_excluded(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            await WorkoutSessionRepository(session).start_draft_session(user.id)
            await session.commit()

        request = _mock_get_request("/api/statistics/records", telegram_id=1)
        response = await api_get_records(request)
        payload = json.loads(response.body)["data"]

        assert payload == []

    async def test_user_param_overrides_caller(self, monkeypatch):
        # GYM-28: ?user= for someone else now requires the caller to be an
        # admin — a plain "trainer" account no longer suffices on its own.
        monkeypatch.setattr(settings, "admin_user_id", 999)
        owner = await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)
        await _add_completed_session(
            owner.id, datetime(2026, 1, 6, 8, 0),
            sets=[{
                "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                "set_number": 1, "weight": 60.0, "reps": 10,
            }],
        )

        request = _mock_get_request(
            "/api/statistics/records?user=lifter", telegram_id=999
        )
        response = await api_get_records(request)
        payload = json.loads(response.body)["data"]

        assert len(payload) == 1
        assert payload[0]["exercise"] == "Жим лежачи"
