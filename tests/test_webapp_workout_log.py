"""Tests for GYM-2: api_save_workout_log (DB primary, Sheets opt-in) and the
Google Sheets sync settings endpoints (src/webapp/server.py).
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from sqlalchemy import select

from src.database.models import Base, WorkoutSession, WorkoutSet
from src.database.repository import UserRepository
from src.database.session import async_session_maker, engine
from tests.test_webapp_auth import build_init_data

from src.webapp.server import (
    api_get_sync_settings,
    api_save_workout_log,
    api_update_sync_settings,
)


@pytest.fixture(autouse=True)
async def _create_tables():
    """Start each test from a clean, empty schema.

    The test DB is a persistent sqlite file shared across the whole run
    (see ``tests/conftest.py``), so leftover rows from other tests would
    otherwise pollute unfiltered queries here.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _make_user(username: str, telegram_id: int, *, sync_enabled: bool = False):
    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user, _ = await user_repo.get_or_create(
            telegram_id=telegram_id, first_name="Test", username=username
        )
        user.sync_workout_to_sheets = sync_enabled
        await session.commit()
        return user


def _mock_request(method: str, path: str, *, telegram_id: int, body: dict) -> web.Request:
    init_data = build_init_data({"id": telegram_id, "first_name": "Test"})
    request = make_mocked_request(
        method, path, headers={"Authorization": init_data}
    )

    async def fake_json():
        return body

    setattr(request, "json", fake_json)
    return request


WORKOUT_BODY = {
    "user": "lifter",
    "day": "1",
    "muscle": "Груди",
    "duration_seconds": 1800,
    "exercises": [
        {
            "exercise": "Жим лежачи",
            "muscle_group": "Груди",
            "planned_sets_reps": "3x10",
            "sets": [
                {"set": 1, "weight": 60, "reps": 10},
                {"set": 2, "weight": 62.5, "reps": 8},
            ],
        }
    ],
}


class TestApiSaveWorkoutLogDbPrimary:
    async def test_unknown_username_returns_404_before_any_write(self):
        request = _mock_request(
            "POST", "/api/workout/log", telegram_id=1, body=WORKOUT_BODY
        )

        with patch(
            "src.webapp.server.GoogleSheetsService"
        ) as mock_sheets_cls, patch(
            "src.webapp.server._sync_workout_to_calendar", new=AsyncMock()
        ):
            response = await api_save_workout_log(request)

            assert response.status == 404
            mock_sheets_cls.assert_not_called()

    async def test_saves_session_and_sets_to_db(self):
        user = await _make_user("lifter", telegram_id=1, sync_enabled=False)
        request = _mock_request(
            "POST", "/api/workout/log", telegram_id=999, body=WORKOUT_BODY
        )

        with patch(
            "src.webapp.server.GoogleSheetsService"
        ) as mock_sheets_cls, patch(
            "src.webapp.server._sync_workout_to_calendar", new=AsyncMock()
        ):
            response = await api_save_workout_log(request)
            payload = json.loads(response.body)

            assert response.status == 200
            assert payload == {"success": True, "synced_to_sheets": False}
            # Sheets must not be touched when sync is disabled (default).
            mock_sheets_cls.assert_not_called()

        async with async_session_maker() as session:
            sessions = (
                await session.execute(
                    select(WorkoutSession).where(WorkoutSession.user_id == user.id)
                )
            ).scalars().all()
            assert len(sessions) == 1
            assert sessions[0].duration_seconds == 1800
            assert sessions[0].day == 1

            sets = (
                await session.execute(
                    select(WorkoutSet).where(WorkoutSet.user_id == user.id)
                )
            ).scalars().all()
            assert len(sets) == 2
            assert {s.weight for s in sets} == {60.0, 62.5}

    async def test_owner_is_resolved_from_body_user_not_caller(self):
        """A trainer (telegram_id 999) logging a workout for `lifter` must
        write it to the *owner's* rows, not their own."""
        owner = await _make_user("lifter", telegram_id=1)
        trainer = await _make_user("trainer", telegram_id=999)

        request = _mock_request(
            "POST", "/api/workout/log", telegram_id=999, body=WORKOUT_BODY
        )

        with patch("src.webapp.server.GoogleSheetsService"), patch(
            "src.webapp.server._sync_workout_to_calendar", new=AsyncMock()
        ):
            response = await api_save_workout_log(request)
            assert response.status == 200

        async with async_session_maker() as session:
            owner_sessions = (
                await session.execute(
                    select(WorkoutSession).where(WorkoutSession.user_id == owner.id)
                )
            ).scalars().all()
            trainer_sessions = (
                await session.execute(
                    select(WorkoutSession).where(WorkoutSession.user_id == trainer.id)
                )
            ).scalars().all()
            assert len(owner_sessions) == 1
            assert len(trainer_sessions) == 0

    async def test_incomplete_sets_are_skipped_in_db_but_not_in_sheets(self):
        await _make_user("lifter", telegram_id=1, sync_enabled=True)
        body = {
            **WORKOUT_BODY,
            "exercises": [
                {
                    "exercise": "Присідання",
                    "muscle_group": "Ноги",
                    "sets": [
                        {"set": 1, "weight": 100, "reps": 5},
                        {"set": 2, "weight": "", "reps": ""},
                    ],
                }
            ],
        }
        request = _mock_request(
            "POST", "/api/workout/log", telegram_id=1, body=body
        )

        mock_sheets = AsyncMock()
        mock_sheets.save_workout_log = AsyncMock(return_value=True)

        with patch(
            "src.webapp.server.GoogleSheetsService", return_value=mock_sheets
        ), patch("src.webapp.server._sync_workout_to_calendar", new=AsyncMock()):
            response = await api_save_workout_log(request)
            payload = json.loads(response.body)

            assert response.status == 200
            assert payload["synced_to_sheets"] is True
            # Both sets (including the incomplete one) are written to Sheets.
            sent_entries = mock_sheets.save_workout_log.call_args.args[1]
            assert len(sent_entries) == 2

        async with async_session_maker() as session:
            sets = (await session.execute(select(WorkoutSet))).scalars().all()
            # Only the complete set is persisted in the DB.
            assert len(sets) == 1
            assert sets[0].weight == 100.0

    async def test_db_failure_returns_500_and_skips_sheets(self):
        await _make_user("lifter", telegram_id=1, sync_enabled=True)
        request = _mock_request(
            "POST", "/api/workout/log", telegram_id=1, body=WORKOUT_BODY
        )

        with patch(
            "src.webapp.server.WorkoutSessionRepository.create_session_with_sets",
            new=AsyncMock(side_effect=RuntimeError("db exploded")),
        ), patch("src.webapp.server.GoogleSheetsService") as mock_sheets_cls:
            response = await api_save_workout_log(request)

            assert response.status == 500
            mock_sheets_cls.assert_not_called()


class TestApiSaveWorkoutLogSheetsOptIn:
    async def test_writes_to_sheets_when_owner_opted_in(self):
        await _make_user("lifter", telegram_id=1, sync_enabled=True)
        request = _mock_request(
            "POST", "/api/workout/log", telegram_id=1, body=WORKOUT_BODY
        )

        mock_sheets = AsyncMock()
        mock_sheets.save_workout_log = AsyncMock(return_value=True)

        with patch(
            "src.webapp.server.GoogleSheetsService", return_value=mock_sheets
        ), patch("src.webapp.server._sync_workout_to_calendar", new=AsyncMock()):
            response = await api_save_workout_log(request)
            payload = json.loads(response.body)

            assert response.status == 200
            assert payload["synced_to_sheets"] is True
            mock_sheets.save_workout_log.assert_awaited_once()

    async def test_sheets_failure_does_not_fail_the_request(self):
        await _make_user("lifter", telegram_id=1, sync_enabled=True)
        request = _mock_request(
            "POST", "/api/workout/log", telegram_id=1, body=WORKOUT_BODY
        )

        mock_sheets = AsyncMock()
        mock_sheets.save_workout_log = AsyncMock(side_effect=RuntimeError("quota"))

        with patch(
            "src.webapp.server.GoogleSheetsService", return_value=mock_sheets
        ), patch("src.webapp.server._sync_workout_to_calendar", new=AsyncMock()):
            response = await api_save_workout_log(request)
            payload = json.loads(response.body)

            assert response.status == 200
            assert payload == {"success": True, "synced_to_sheets": False}

        async with async_session_maker() as session:
            sets = (await session.execute(select(WorkoutSet))).scalars().all()
            assert len(sets) == 2


class TestSyncSettingsEndpoints:
    async def test_get_defaults_to_disabled(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "GET", "/api/user/sync-settings", telegram_id=1, body={}
        )

        response = await api_get_sync_settings(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload == {
            "success": True,
            "data": {"sync_workout_to_sheets": False},
        }

    async def test_get_unknown_user_returns_404(self):
        request = _mock_request(
            "GET", "/api/user/sync-settings", telegram_id=1234, body={}
        )

        response = await api_get_sync_settings(request)
        assert response.status == 404

    async def test_update_enables_and_persists(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "POST",
            "/api/user/sync-settings",
            telegram_id=1,
            body={"sync_workout_to_sheets": True},
        )

        response = await api_update_sync_settings(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload["data"]["sync_workout_to_sheets"] is True

        async with async_session_maker() as session:
            user = await UserRepository(session).get_by_telegram_id(1)
            assert user.sync_workout_to_sheets is True
