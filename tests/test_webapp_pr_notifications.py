"""Tests for GYM-9: PR notifications sent from api_save_workout_log
(src/webapp/server.py).
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.database.models import Base
from src.database.session import engine
from src.webapp.server import api_save_workout_log, get_bot_instance, set_bot_instance
from tests.test_webapp_workout_log import WORKOUT_BODY, _make_user, _mock_request


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture(autouse=True)
def _reset_bot_instance():
    yield
    set_bot_instance(None)


async def _save_workout(telegram_id: int, body: dict = WORKOUT_BODY):
    request = _mock_request(
        "POST", "/api/workout/log", telegram_id=telegram_id, body=body
    )
    with patch("src.webapp.server.GoogleSheetsService"), patch(
        "src.webapp.server._sync_workout_to_calendar", new=AsyncMock()
    ):
        return await api_save_workout_log(request)


class TestNewPrNotifications:
    async def test_sends_one_message_per_distinct_winning_set(self):
        # WORKOUT_BODY logs 62.5kg x8 and 60kg x10 for "Жим лежачи".
        # 1RM: 60*(1+10/30)=80 beats 62.5*(1+8/30)=79.17, so the two PR
        # winners are 62.5x8 (max_weight) and 60x10 (max_reps + best 1RM,
        # which collapse into one message since they're the same set).
        owner = await _make_user("lifter", telegram_id=1)
        bot = AsyncMock()
        set_bot_instance(bot)

        response = await _save_workout(telegram_id=1)
        assert response.status == 200

        assert bot.send_message.await_count == 2
        recipients = {call.args[0] for call in bot.send_message.await_args_list}
        assert recipients == {owner.telegram_id}

        texts = {call.args[1] for call in bot.send_message.await_args_list}
        assert all(t.startswith("🏆 Новий рекорд! Жим лежачи:") for t in texts)
        assert any("62.5 кг × 8" in t for t in texts)
        assert any("60 кг × 10" in t for t in texts)

    async def test_no_message_when_not_beating_an_existing_record(self):
        await _make_user("lifter", telegram_id=1)
        await _save_workout(telegram_id=1)  # establishes the PRs

        bot = AsyncMock()
        set_bot_instance(bot)

        # Logging the exact same numbers again doesn't set a NEW record.
        response = await _save_workout(telegram_id=1)

        assert response.status == 200
        bot.send_message.assert_not_awaited()

    async def test_notifies_the_owner_not_the_trainer(self):
        owner = await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)
        bot = AsyncMock()
        set_bot_instance(bot)

        # Trainer (999) logs the workout on behalf of "lifter".
        response = await _save_workout(telegram_id=999)

        assert response.status == 200
        assert bot.send_message.await_count > 0
        for call in bot.send_message.await_args_list:
            assert call.args[0] == owner.telegram_id

    async def test_notification_failure_does_not_fail_the_save(self):
        await _make_user("lifter", telegram_id=1)
        bot = AsyncMock()
        bot.send_message = AsyncMock(side_effect=RuntimeError("telegram down"))
        set_bot_instance(bot)

        response = await _save_workout(telegram_id=1)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload["success"] is True

    async def test_no_bot_instance_does_not_crash(self):
        await _make_user("lifter", telegram_id=1)
        assert get_bot_instance() is None

        response = await _save_workout(telegram_id=1)

        assert response.status == 200
