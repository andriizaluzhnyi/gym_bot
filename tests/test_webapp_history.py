"""Tests for GYM-10: GET /api/statistics/history[/{session_id}]
(src/webapp/server.py).
"""

import json
from datetime import datetime

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.database.models import Base
from src.database.repository import UserRepository, WorkoutSessionRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import api_get_history, api_get_history_session
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
        workout_session = await WorkoutSessionRepository(
            session
        ).create_session_with_sets(
            user_id=user_id, performed_at=performed_at, sets=sets, **kwargs
        )
        await session.commit()
        return workout_session.id


def _mock_get_request(
    path: str, *, telegram_id: int, match_info: dict | None = None
) -> web.Request:
    init_data = build_init_data({"id": telegram_id, "first_name": "Test"})
    return make_mocked_request(
        "GET",
        path,
        headers={"Authorization": init_data},
        match_info=match_info or {},
    )


class TestHistoryListAuthAndValidation:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "GET", "/api/statistics/history", headers={"Authorization": "garbage"}
        )
        response = await api_get_history(request)
        assert response.status == 401

    async def test_unknown_caller_returns_404(self):
        request = _mock_get_request("/api/statistics/history", telegram_id=999)
        response = await api_get_history(request)
        assert response.status == 404

    async def test_invalid_limit_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request(
            "/api/statistics/history?limit=abc", telegram_id=1
        )
        response = await api_get_history(request)
        assert response.status == 400

    async def test_negative_offset_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request(
            "/api/statistics/history?offset=-1", telegram_id=1
        )
        response = await api_get_history(request)
        assert response.status == 400


class TestHistoryListEmpty:
    async def test_no_sessions_returns_empty_list(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request("/api/statistics/history", telegram_id=1)
        response = await api_get_history(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload == {"success": True, "data": []}

    async def test_draft_session_is_excluded(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            await WorkoutSessionRepository(session).start_draft_session(user.id)
            await session.commit()

        request = _mock_get_request("/api/statistics/history", telegram_id=1)
        response = await api_get_history(request)
        payload = json.loads(response.body)["data"]

        assert payload == []


class TestHistoryListSummary:
    async def test_session_summary_shape(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id, datetime(2026, 1, 6, 8, 0),
            sets=[
                {
                    "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                    "set_number": 1, "weight": 80.0, "reps": 5,
                },
                {
                    "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                    "set_number": 2, "weight": 80.0, "reps": 4,
                },
                {
                    "exercise_name": "Розводка", "muscle_group": "Груди",
                    "set_number": 1, "weight": 20.0, "reps": 12,
                },
            ],
            muscle_group="Груди", duration_seconds=3600,
        )

        request = _mock_get_request("/api/statistics/history", telegram_id=1)
        response = await api_get_history(request)
        payload = json.loads(response.body)["data"]

        assert response.status == 200
        assert len(payload) == 1
        row = payload[0]
        assert row["date"] == "2026-01-06"
        assert row["muscle_group"] == "Груди"
        assert row["exercises_count"] == 2
        assert row["sets_count"] == 3
        assert row["total_volume"] == 80.0 * 5 + 80.0 * 4 + 20.0 * 12
        assert row["duration_minutes"] == 60.0
        assert isinstance(row["session_id"], int)

    async def test_missing_duration_defaults_to_zero(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id, datetime(2026, 1, 6, 8, 0),
            sets=[{
                "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                "set_number": 1, "weight": 80.0, "reps": 5,
            }],
        )

        request = _mock_get_request("/api/statistics/history", telegram_id=1)
        response = await api_get_history(request)
        row = json.loads(response.body)["data"][0]

        assert row["duration_minutes"] == 0

    async def test_most_recent_first(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id, datetime(2026, 1, 1, 8, 0),
            sets=[{
                "exercise_name": "A", "muscle_group": "Груди",
                "set_number": 1, "weight": 10.0, "reps": 5,
            }],
        )
        await _add_completed_session(
            user.id, datetime(2026, 1, 10, 8, 0),
            sets=[{
                "exercise_name": "B", "muscle_group": "Ноги",
                "set_number": 1, "weight": 10.0, "reps": 5,
            }],
        )

        request = _mock_get_request("/api/statistics/history", telegram_id=1)
        response = await api_get_history(request)
        payload = json.loads(response.body)["data"]

        assert [row["date"] for row in payload] == ["2026-01-10", "2026-01-01"]

    async def test_user_param_overrides_caller(self):
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
            "/api/statistics/history?user=lifter", telegram_id=999
        )
        response = await api_get_history(request)
        payload = json.loads(response.body)["data"]

        assert len(payload) == 1


class TestHistoryListPagination:
    async def test_limit_and_offset(self):
        user = await _make_user("lifter", telegram_id=1)
        for day in range(1, 6):
            await _add_completed_session(
                user.id, datetime(2026, 1, day, 8, 0),
                sets=[{
                    "exercise_name": "A", "muscle_group": "Груди",
                    "set_number": 1, "weight": 10.0, "reps": 5,
                }],
            )

        request = _mock_get_request(
            "/api/statistics/history?limit=2&offset=1", telegram_id=1
        )
        response = await api_get_history(request)
        payload = json.loads(response.body)["data"]

        # 5 sessions, most-recent first: Jan 5, 4, 3, 2, 1 — offset 1, limit 2
        # skips Jan 5 and returns Jan 4, Jan 3.
        assert [row["date"] for row in payload] == ["2026-01-04", "2026-01-03"]

    async def test_limit_is_capped(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(
            user.id, datetime(2026, 1, 6, 8, 0),
            sets=[{
                "exercise_name": "A", "muscle_group": "Груди",
                "set_number": 1, "weight": 10.0, "reps": 5,
            }],
        )

        request = _mock_get_request(
            "/api/statistics/history?limit=99999", telegram_id=1
        )
        response = await api_get_history(request)

        assert response.status == 200


class TestHistorySessionDetail:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "GET", "/api/statistics/history/1",
            headers={"Authorization": "garbage"}, match_info={"session_id": "1"},
        )
        response = await api_get_history_session(request)
        assert response.status == 401

    async def test_non_numeric_session_id_returns_400(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request(
            "/api/statistics/history/abc", telegram_id=1,
            match_info={"session_id": "abc"},
        )
        response = await api_get_history_session(request)
        assert response.status == 400

    async def test_unknown_session_returns_404(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request(
            "/api/statistics/history/12345", telegram_id=1,
            match_info={"session_id": "12345"},
        )
        response = await api_get_history_session(request)
        assert response.status == 404

    async def test_other_users_session_returns_404(self):
        owner = await _make_user("lifter", telegram_id=1)
        await _make_user("intruder", telegram_id=2)
        session_id = await _add_completed_session(
            owner.id, datetime(2026, 1, 6, 8, 0),
            sets=[{
                "exercise_name": "A", "muscle_group": "Груди",
                "set_number": 1, "weight": 10.0, "reps": 5,
            }],
        )

        request = _mock_get_request(
            f"/api/statistics/history/{session_id}", telegram_id=2,
            match_info={"session_id": str(session_id)},
        )
        response = await api_get_history_session(request)
        assert response.status == 404

    async def test_draft_session_returns_404(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            draft = await WorkoutSessionRepository(session).start_draft_session(
                user.id
            )
            await session.commit()
            draft_id = draft.id

        request = _mock_get_request(
            f"/api/statistics/history/{draft_id}", telegram_id=1,
            match_info={"session_id": str(draft_id)},
        )
        response = await api_get_history_session(request)
        assert response.status == 404

    async def test_session_detail_groups_exercises_and_sets(self):
        user = await _make_user("lifter", telegram_id=1)
        session_id = await _add_completed_session(
            user.id, datetime(2026, 1, 6, 8, 0),
            sets=[
                {
                    "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                    "set_number": 1, "weight": 80.0, "reps": 5,
                },
                {
                    "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                    "set_number": 2, "weight": 80.0, "reps": 4,
                },
                {
                    "exercise_name": "Розводка", "muscle_group": "Груди",
                    "set_number": 1, "weight": 20.0, "reps": 12,
                },
            ],
            muscle_group="Груди", duration_seconds=1800,
        )

        request = _mock_get_request(
            f"/api/statistics/history/{session_id}", telegram_id=1,
            match_info={"session_id": str(session_id)},
        )
        response = await api_get_history_session(request)
        payload = json.loads(response.body)["data"]

        assert response.status == 200
        assert payload["session_id"] == session_id
        assert payload["date"] == "2026-01-06"
        assert payload["duration_minutes"] == 30.0
        assert len(payload["exercises"]) == 2

        bench = payload["exercises"][0]
        assert bench["exercise"] == "Жим лежачи"
        assert bench["muscle_group"] == "Груди"
        assert bench["sets"] == [
            {"set": 1, "weight": 80.0, "reps": 5},
            {"set": 2, "weight": 80.0, "reps": 4},
        ]

        flyes = payload["exercises"][1]
        assert flyes["exercise"] == "Розводка"
        assert flyes["sets"] == [{"set": 1, "weight": 20.0, "reps": 12}]

    async def test_user_param_overrides_caller(self):
        owner = await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)
        session_id = await _add_completed_session(
            owner.id, datetime(2026, 1, 6, 8, 0),
            sets=[{
                "exercise_name": "A", "muscle_group": "Груди",
                "set_number": 1, "weight": 10.0, "reps": 5,
            }],
        )

        request = _mock_get_request(
            f"/api/statistics/history/{session_id}?user=lifter",
            telegram_id=999, match_info={"session_id": str(session_id)},
        )
        response = await api_get_history_session(request)
        payload = json.loads(response.body)["data"]

        assert response.status == 200
        assert payload["session_id"] == session_id
