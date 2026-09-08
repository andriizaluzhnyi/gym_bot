"""Tests for GYM-31: `GET /api/exercises/{id}` (src/webapp/server.py) —
the exercise-details endpoint behind `/workout`'s "ⓘ" bottom sheet.
"""

import json

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.database.models import Base
from src.database.repository import ExerciseRepository, UserRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import api_get_exercise
from tests.test_webapp_auth import build_init_data

import pytest


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


async def _make_exercise(
    name: str, *, muscle_group: str | None = None, description: str | None = None,
    image_url: str | None = None, video_url: str | None = None,
) -> int:
    async with async_session_maker() as session:
        exercise = await ExerciseRepository(session).get_or_create_by_name(
            name, muscle_group=muscle_group
        )
        exercise.description = description
        exercise.image_url = image_url
        exercise.video_url = video_url
        await session.commit()
        return exercise.id


def _mock_get_request(path: str, *, telegram_id: int) -> web.Request:
    init_data = build_init_data({"id": telegram_id, "first_name": "Test"})
    request = make_mocked_request(
        "GET", path, headers={"Authorization": init_data}
    )
    # api_get_exercise reads the id from the path (`{id}`), which
    # make_mocked_request doesn't populate from `path` alone — set
    # match_info directly, the same way aiohttp's router would.
    request.match_info["id"] = path.rstrip("/").rsplit("/", 1)[-1]
    return request


class TestApiGetExercise:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "GET", "/api/exercises/1", headers={"Authorization": "garbage"}
        )
        request.match_info["id"] = "1"
        response = await api_get_exercise(request)
        assert response.status == 401

    async def test_non_numeric_id_returns_400(self):
        await _make_user(1)
        request = _mock_get_request("/api/exercises/not-a-number", telegram_id=1)
        response = await api_get_exercise(request)
        assert response.status == 400

    async def test_unknown_id_returns_404(self):
        await _make_user(1)
        request = _mock_get_request("/api/exercises/999", telegram_id=1)
        response = await api_get_exercise(request)
        assert response.status == 404

    async def test_filled_in_row_returns_all_fields(self):
        await _make_user(1)
        exercise_id = await _make_exercise(
            "Жим лежачи",
            muscle_group="🏋️ Груди",
            description="Лягти на лаву, опустити штангу до грудей.",
            image_url="https://example.com/bench.jpg",
            video_url="https://youtube.com/watch?v=abc",
        )

        request = _mock_get_request(f"/api/exercises/{exercise_id}", telegram_id=1)
        response = await api_get_exercise(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload == {
            "success": True,
            "data": {
                "id": exercise_id,
                "name": "Жим лежачи",
                "muscle_group": "🏋️ Груди",
                "description": "Лягти на лаву, опустити штангу до грудей.",
                "image_url": "https://example.com/bench.jpg",
                "video_url": "https://youtube.com/watch?v=abc",
            },
        }

    async def test_empty_row_returns_null_detail_fields(self):
        await _make_user(1)
        exercise_id = await _make_exercise("Присідання", muscle_group="🦵 Ноги")

        request = _mock_get_request(f"/api/exercises/{exercise_id}", telegram_id=1)
        response = await api_get_exercise(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload["data"] == {
            "id": exercise_id,
            "name": "Присідання",
            "muscle_group": "🦵 Ноги",
            "description": None,
            "image_url": None,
            "video_url": None,
        }

    async def test_no_ownership_check_any_authenticated_caller_can_read(self):
        # GYM-31: the catalog is shared — no admin/owner gating, unlike
        # program/statistics endpoints (_resolve_program_owner).
        await _make_user(1)
        exercise_id = await _make_exercise("Тяга", muscle_group="🦴 Спина")

        request = _mock_get_request(f"/api/exercises/{exercise_id}", telegram_id=1)
        response = await api_get_exercise(request)
        assert response.status == 200
