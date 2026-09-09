"""Tests for GYM-47: the workout rest-timer reminder no longer fires for a
workout that's already been completed or whose timer was stopped/replaced
(``api_start_rest_timer`` / ``api_cancel_rest_timer``,
``src/webapp/server.py``).

Durations in these tests are small real sleeps (tenths of a second), not
mocked ``asyncio.sleep`` — ``asyncio.sleep`` is a bare module-level
reference shared process-wide, so patching it here would also break
pytest-asyncio's own internals. Timings are chosen with enough margin
(≥3x) to not be flaky on a loaded CI box.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.database.models import Base
from src.database.repository import WorkoutSessionRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import (
    _rest_timer_tasks,
    api_cancel_rest_timer,
    api_save_workout_log,
    api_start_rest_timer,
)
from tests.test_webapp_auth import build_init_data
from tests.test_webapp_workout_log import WORKOUT_BODY, _make_user


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    _rest_timer_tasks.clear()
    yield
    _rest_timer_tasks.clear()


def _mock_request(
    method: str, path: str, *, telegram_id: int, body: dict | None = None
) -> web.Request:
    init_data = build_init_data({"id": telegram_id, "first_name": "Test"})
    request = make_mocked_request(
        method, path, headers={"Authorization": init_data}
    )
    if body is not None:
        async def fake_json():
            return body

        request.json = fake_json  # type: ignore[method-assign, assignment]
    return request


class TestApiStartRestTimer:
    async def test_no_session_id_sends_unconditionally(self):
        """Legacy behavior: no `session_id` given, nothing to check — the
        reminder still sends after the delay, same as before this ticket.
        """
        await _make_user("lifter", telegram_id=1)
        bot = AsyncMock()
        with patch("src.webapp.server.get_bot_instance", return_value=bot):
            request = _mock_request(
                "POST", "/api/workout/rest-timer", telegram_id=1,
                body={"duration_seconds": 0.05, "user": "lifter", "day": "1"},
            )
            response = await api_start_rest_timer(request)
            assert response.status == 200

            await asyncio.sleep(0.2)

        bot.send_message.assert_called_once()

    async def test_active_session_still_gets_the_reminder(self):
        owner = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            draft = await WorkoutSessionRepository(session).start_draft_session(
                owner.id, day=1, muscle_group="Груди"
            )
            await session.commit()
            session_id = draft.id

        bot = AsyncMock()
        with patch("src.webapp.server.get_bot_instance", return_value=bot):
            request = _mock_request(
                "POST", "/api/workout/rest-timer", telegram_id=1,
                body={
                    "duration_seconds": 0.05,
                    "user": "lifter",
                    "day": "1",
                    "session_id": session_id,
                },
            )
            await api_start_rest_timer(request)
            await asyncio.sleep(0.2)

        bot.send_message.assert_called_once()

    async def test_completed_session_before_timer_fires_skips_notification(self):
        """The scenario this ticket exists for: the workout's last set
        starts a rest timer, and the user taps "Завершити тренування"
        (which completes the session) before the timer's delay elapses.
        """
        owner = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            draft = await WorkoutSessionRepository(session).start_draft_session(
                owner.id, day=1, muscle_group="Груди"
            )
            await session.commit()
            session_id = draft.id

        bot = AsyncMock()
        with patch("src.webapp.server.get_bot_instance", return_value=bot):
            request = _mock_request(
                "POST", "/api/workout/rest-timer", telegram_id=1,
                body={
                    "duration_seconds": 0.1,
                    "user": "lifter",
                    "day": "1",
                    "session_id": session_id,
                },
            )
            await api_start_rest_timer(request)

            # Complete the session before the timer's 0.1s delay elapses.
            async with async_session_maker() as session:
                await WorkoutSessionRepository(session).complete_session(
                    session_id, owner.id, duration_seconds=60,
                    day=1, muscle_group="Груди",
                )
                await session.commit()

            await asyncio.sleep(0.3)

        bot.send_message.assert_not_called()

    async def test_missing_session_skips_notification(self):
        await _make_user("lifter", telegram_id=1)
        bot = AsyncMock()
        with patch("src.webapp.server.get_bot_instance", return_value=bot):
            request = _mock_request(
                "POST", "/api/workout/rest-timer", telegram_id=1,
                body={
                    "duration_seconds": 0.05,
                    "user": "lifter",
                    "day": "1",
                    "session_id": 999999,
                },
            )
            await api_start_rest_timer(request)
            await asyncio.sleep(0.2)

        bot.send_message.assert_not_called()

    async def test_starting_a_new_timer_cancels_the_previous_pending_one(self):
        await _make_user("lifter", telegram_id=1)
        bot = AsyncMock()
        with patch("src.webapp.server.get_bot_instance", return_value=bot):
            first = _mock_request(
                "POST", "/api/workout/rest-timer", telegram_id=1,
                body={"duration_seconds": 0.3, "user": "lifter", "day": "1"},
            )
            await api_start_rest_timer(first)

            # Replace it before it fires — the client only ever runs one
            # rest timer at a time, so the first is now stale.
            second = _mock_request(
                "POST", "/api/workout/rest-timer", telegram_id=1,
                body={"duration_seconds": 0.05, "user": "lifter", "day": "1"},
            )
            await api_start_rest_timer(second)

            await asyncio.sleep(0.5)

        # Only the second timer's reminder should have fired.
        bot.send_message.assert_called_once()

    async def test_missing_bot_instance_returns_503(self):
        await _make_user("lifter", telegram_id=1)
        with patch("src.webapp.server.get_bot_instance", return_value=None):
            request = _mock_request(
                "POST", "/api/workout/rest-timer", telegram_id=1,
                body={"duration_seconds": 60, "user": "lifter", "day": "1"},
            )
            response = await api_start_rest_timer(request)
        assert response.status == 503

    async def test_unauthorized_without_init_data(self):
        request = make_mocked_request("POST", "/api/workout/rest-timer")
        response = await api_start_rest_timer(request)
        assert response.status == 401


class TestApiCancelRestTimer:
    async def test_cancels_pending_timer(self):
        await _make_user("lifter", telegram_id=1)
        bot = AsyncMock()
        with patch("src.webapp.server.get_bot_instance", return_value=bot):
            start_request = _mock_request(
                "POST", "/api/workout/rest-timer", telegram_id=1,
                body={"duration_seconds": 0.1, "user": "lifter", "day": "1"},
            )
            await api_start_rest_timer(start_request)

            cancel_request = _mock_request(
                "DELETE", "/api/workout/rest-timer", telegram_id=1
            )
            response = await api_cancel_rest_timer(cancel_request)
            assert response.status == 200

            await asyncio.sleep(0.3)

        bot.send_message.assert_not_called()

    async def test_idempotent_with_no_pending_timer(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_request("DELETE", "/api/workout/rest-timer", telegram_id=1)
        response = await api_cancel_rest_timer(request)
        assert response.status == 200
        payload = json.loads(response.body)
        assert payload["success"] is True

    async def test_unauthorized_without_init_data(self):
        request = make_mocked_request("DELETE", "/api/workout/rest-timer")
        response = await api_cancel_rest_timer(request)
        assert response.status == 401


class TestSaveWorkoutLogCancelsRestTimer:
    async def test_successful_save_cancels_callers_pending_timer(self):
        await _make_user("lifter", telegram_id=1)
        bot = AsyncMock()
        with patch("src.webapp.server.get_bot_instance", return_value=bot):
            start_request = _mock_request(
                "POST", "/api/workout/rest-timer", telegram_id=1,
                body={"duration_seconds": 0.15, "user": "lifter", "day": "1"},
            )
            await api_start_rest_timer(start_request)

            log_request = _mock_request(
                "POST", "/api/workout/log", telegram_id=1, body=WORKOUT_BODY
            )
            save_response = await api_save_workout_log(log_request)
            assert save_response.status == 200

            await asyncio.sleep(0.3)

        # `api_save_workout_log` itself sends unrelated PR/achievement
        # `send_message` calls (GYM-9/GYM-13a) — assert on message content,
        # not call count, so this test isn't coupled to that behavior.
        rest_timer_calls = [
            call for call in bot.send_message.call_args_list
            if "Час відпочинку" in call.args[1]
        ]
        assert rest_timer_calls == []
