"""Tests for GYM-2c: DB-backed draft workout sessions (autosave + resume)
via ``/api/workout/session/start`` and ``/api/workout/session/exercise``,
and their reconciliation with ``/api/workout/log`` (src/webapp/server.py).
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.database.models import Base, WorkoutSession, WorkoutSet
from src.database.repository import WorkoutSessionRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import (
    api_save_workout_log,
    api_start_workout_session,
    api_sync_workout_session_exercise,
)
from tests.test_webapp_workout_log import WORKOUT_BODY, _make_user, _mock_request


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


class TestStartWorkoutSession:
    async def test_unknown_username_returns_404(self):
        request = _mock_request(
            "POST",
            "/api/workout/session/start",
            telegram_id=1,
            body={"user": "ghost", "day": "1", "muscle": ""},
        )
        response = await api_start_workout_session(request)
        assert response.status == 404

    async def test_first_open_creates_fresh_draft(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request(
            "POST",
            "/api/workout/session/start",
            telegram_id=1,
            body={"user": "lifter", "day": "1", "muscle": ""},
        )

        response = await api_start_workout_session(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload["data"]["resumed"] is False
        assert payload["data"]["sets_by_exercise"] == {}
        assert isinstance(payload["data"]["session_id"], int)

        async with async_session_maker() as session:
            row = await session.get(WorkoutSession, payload["data"]["session_id"])
            assert row is not None
            assert row.completed_at is None

    async def test_reopening_resumes_the_same_draft_with_its_sets(self):
        await _make_user("lifter", telegram_id=1)
        start_request = _mock_request(
            "POST",
            "/api/workout/session/start",
            telegram_id=1,
            body={"user": "lifter", "day": "1", "muscle": ""},
        )
        first = json.loads((await api_start_workout_session(start_request)).body)
        session_id = first["data"]["session_id"]

        sync_request = _mock_request(
            "POST",
            "/api/workout/session/exercise",
            telegram_id=1,
            body={
                "session_id": session_id,
                "exercise": "Жим лежачи",
                "muscle_group": "Груди",
                "planned_sets_reps": "3x10",
                "sets": [{"set": 1, "weight": 60, "reps": 10}],
            },
        )
        await api_sync_workout_session_exercise(sync_request)

        reopen_request = _mock_request(
            "POST",
            "/api/workout/session/start",
            telegram_id=1,
            body={"user": "lifter", "day": "1", "muscle": ""},
        )
        second = json.loads((await api_start_workout_session(reopen_request)).body)

        assert second["data"]["session_id"] == session_id
        assert second["data"]["resumed"] is True
        assert second["data"]["sets_by_exercise"] == {
            "Жим лежачи": [{"set": 1, "weight": 60.0, "reps": 10}]
        }

    async def test_different_day_does_not_resume_other_drafts_session(self):
        await _make_user("lifter", telegram_id=1)
        day1 = _mock_request(
            "POST",
            "/api/workout/session/start",
            telegram_id=1,
            body={"user": "lifter", "day": "1", "muscle": ""},
        )
        first = json.loads((await api_start_workout_session(day1)).body)

        day2 = _mock_request(
            "POST",
            "/api/workout/session/start",
            telegram_id=1,
            body={"user": "lifter", "day": "2", "muscle": ""},
        )
        second = json.loads((await api_start_workout_session(day2)).body)

        assert second["data"]["resumed"] is False
        assert second["data"]["session_id"] != first["data"]["session_id"]


class TestSyncWorkoutSessionExercise:
    async def test_unknown_session_returns_404(self):
        request = _mock_request(
            "POST",
            "/api/workout/session/exercise",
            telegram_id=1,
            body={
                "session_id": 999999,
                "exercise": "Жим лежачи",
                "sets": [{"set": 1, "weight": 60, "reps": 10}],
            },
        )
        response = await api_sync_workout_session_exercise(request)
        assert response.status == 404

    async def test_completed_session_returns_409(self):
        owner = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            repo = WorkoutSessionRepository(session)
            draft = await repo.start_draft_session(owner.id)
            await repo.complete_session(draft.id, owner.id)
            await session.commit()
            session_id = draft.id

        request = _mock_request(
            "POST",
            "/api/workout/session/exercise",
            telegram_id=1,
            body={
                "session_id": session_id,
                "exercise": "Жим лежачи",
                "sets": [{"set": 1, "weight": 60, "reps": 10}],
            },
        )
        response = await api_sync_workout_session_exercise(request)
        assert response.status == 409

    async def test_saves_sets_and_skips_incomplete_ones(self):
        owner = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            draft = await WorkoutSessionRepository(session).start_draft_session(owner.id)
            await session.commit()
            session_id = draft.id

        request = _mock_request(
            "POST",
            "/api/workout/session/exercise",
            telegram_id=1,
            body={
                "session_id": session_id,
                "exercise": "Присідання",
                "muscle_group": "Ноги",
                "planned_sets_reps": "3x5",
                "sets": [
                    {"set": 1, "weight": 100, "reps": 5},
                    {"set": 2, "weight": "", "reps": ""},
                ],
            },
        )
        response = await api_sync_workout_session_exercise(request)
        assert response.status == 200

        async with async_session_maker() as session:
            rows = (
                await session.execute(
                    select(WorkoutSet).where(WorkoutSet.session_id == session_id)
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].weight == 100.0


class TestFinishReconcilesDraft:
    async def test_finish_completes_the_draft_instead_of_creating_a_new_session(self):
        owner = await _make_user("lifter", telegram_id=1)
        start_request = _mock_request(
            "POST",
            "/api/workout/session/start",
            telegram_id=1,
            body={"user": "lifter", "day": "1", "muscle": "Груди"},
        )
        started = json.loads((await api_start_workout_session(start_request)).body)
        session_id = started["data"]["session_id"]

        finish_request = _mock_request(
            "POST", "/api/workout/log", telegram_id=1, body=WORKOUT_BODY
        )
        with patch("src.webapp.server.GoogleSheetsService"), patch(
            "src.webapp.server._sync_workout_to_calendar", new=AsyncMock()
        ):
            response = await api_save_workout_log(finish_request)
            assert response.status == 200

        async with async_session_maker() as session:
            sessions = (
                await session.execute(
                    select(WorkoutSession).where(WorkoutSession.user_id == owner.id)
                )
            ).scalars().all()
            # The draft was reused and completed, not duplicated.
            assert len(sessions) == 1
            assert sessions[0].id == session_id
            assert sessions[0].completed_at is not None

            sets = (
                await session.execute(
                    select(WorkoutSet).where(WorkoutSet.session_id == session_id)
                )
            ).scalars().all()
            assert len(sets) == 2

    async def test_finish_without_a_draft_falls_back_to_one_shot_create(self):
        """Older client / autosave never ran: finish still works standalone."""
        owner = await _make_user("lifter", telegram_id=1)
        finish_request = _mock_request(
            "POST", "/api/workout/log", telegram_id=1, body=WORKOUT_BODY
        )
        with patch("src.webapp.server.GoogleSheetsService"), patch(
            "src.webapp.server._sync_workout_to_calendar", new=AsyncMock()
        ):
            response = await api_save_workout_log(finish_request)
            assert response.status == 200

        async with async_session_maker() as session:
            sessions = (
                await session.execute(
                    select(WorkoutSession).where(WorkoutSession.user_id == owner.id)
                )
            ).scalars().all()
            assert len(sessions) == 1
            assert sessions[0].completed_at is not None

    async def test_edits_made_after_last_autosave_are_still_captured_at_finish(self):
        """Finish sends the full current state, so it corrects any set the
        autosave call for it never reached (e.g. a dropped request)."""
        await _make_user("lifter", telegram_id=1)
        start_request = _mock_request(
            "POST",
            "/api/workout/session/start",
            telegram_id=1,
            body={"user": "lifter", "day": "1", "muscle": "Груди"},
        )
        started = json.loads((await api_start_workout_session(start_request)).body)
        session_id = started["data"]["session_id"]

        # Autosave captured only the first set...
        sync_request = _mock_request(
            "POST",
            "/api/workout/session/exercise",
            telegram_id=1,
            body={
                "session_id": session_id,
                "exercise": "Жим лежачи",
                "muscle_group": "Груди",
                "planned_sets_reps": "3x10",
                "sets": [{"set": 1, "weight": 60, "reps": 10}],
            },
        )
        await api_sync_workout_session_exercise(sync_request)

        # ...but by the time of finish, the user had also logged a 2nd set.
        finish_request = _mock_request(
            "POST", "/api/workout/log", telegram_id=1, body=WORKOUT_BODY
        )
        with patch("src.webapp.server.GoogleSheetsService"), patch(
            "src.webapp.server._sync_workout_to_calendar", new=AsyncMock()
        ):
            response = await api_save_workout_log(finish_request)
            assert response.status == 200

        async with async_session_maker() as session:
            sets = (
                await session.execute(
                    select(WorkoutSet).where(WorkoutSet.session_id == session_id)
                )
            ).scalars().all()
            assert len(sets) == 2
            assert {s.weight for s in sets} == {60.0, 62.5}
