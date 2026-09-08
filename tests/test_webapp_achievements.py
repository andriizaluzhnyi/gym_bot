"""Tests for GYM-13a/GYM-13b: AchievementsService / UserAchievementRepository
(DB-backed), their wiring into api_save_workout_log, and
GET /api/statistics/achievements (src/webapp/server.py).

evaluate_achievements() itself (which achievements a given history
satisfies) is unit-tested without a DB in test_achievements.py; these
tests cover persistence (unlocking writes a row, idempotency, the unique
constraint), the end-to-end save-a-workout notification flow, and the
catalog-merge endpoint instead.
"""

import json
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request
from sqlalchemy.exc import IntegrityError

from src.database.models import Base
from src.database.repository import UserAchievementRepository, WorkoutSessionRepository
from src.database.session import async_session_maker, engine
from src.services.achievements import ACHIEVEMENTS, AchievementsService
from src.webapp.server import (
    api_get_achievements,
    api_save_workout_log,
    get_bot_instance,
    set_bot_instance,
)
from tests.test_webapp_auth import build_init_data
from tests.test_webapp_workout_log import WORKOUT_BODY, _make_user, _mock_request

TZ = "Europe/Kyiv"


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


async def _add_completed_session(user_id, performed_at: datetime, **kwargs):
    async with async_session_maker() as session:
        await WorkoutSessionRepository(session).create_session_with_sets(
            user_id=user_id, performed_at=performed_at, sets=[{
                "exercise_name": "Жим лежачи", "muscle_group": "Груди",
                "set_number": 1, "weight": 60.0, "reps": 10,
            }], **kwargs,
        )
        await session.commit()


async def _save_workout(telegram_id: int, body: dict = WORKOUT_BODY):
    request = _mock_request(
        "POST", "/api/workout/log", telegram_id=telegram_id, body=body
    )
    with patch("src.webapp.server.GoogleSheetsService"), patch(
        "src.webapp.server._sync_workout_to_calendar", new=AsyncMock()
    ):
        return await api_save_workout_log(request)


class TestUserAchievementRepository:
    async def test_get_unlocked_codes_empty_for_new_user(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            codes = await UserAchievementRepository(session).get_unlocked_codes(
                user.id
            )
        assert codes == set()

    async def test_unlock_persists_and_is_visible_afterwards(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            await UserAchievementRepository(session).unlock(user.id, "FIRST_PR")
            await session.commit()

        async with async_session_maker() as session:
            codes = await UserAchievementRepository(session).get_unlocked_codes(
                user.id
            )
        assert codes == {"FIRST_PR"}

    async def test_duplicate_unlock_violates_unique_constraint(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            repo = UserAchievementRepository(session)
            await repo.unlock(user.id, "FIRST_PR")
            await session.commit()

        async with async_session_maker() as session:
            with pytest.raises(IntegrityError):
                await UserAchievementRepository(session).unlock(user.id, "FIRST_PR")
                await session.commit()


class TestAchievementsServiceCheckAndUnlock:
    async def test_no_history_unlocks_nothing(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            unlocked = await AchievementsService(session).check_and_unlock(
                user.id, date(2026, 1, 15), TZ
            )
            await session.commit()

        assert unlocked == []

    async def test_first_session_unlocks_and_persists_first_pr(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(user.id, datetime(2026, 1, 1, 10, 0))

        async with async_session_maker() as session:
            unlocked = await AchievementsService(session).check_and_unlock(
                user.id, date(2026, 1, 1), TZ
            )
            await session.commit()

        assert [a.code for a in unlocked] == ["FIRST_PR"]

        async with async_session_maker() as session:
            codes = await UserAchievementRepository(session).get_unlocked_codes(
                user.id
            )
        assert codes == {"FIRST_PR"}

    async def test_second_call_does_not_re_unlock_the_same_achievement(self):
        user = await _make_user("lifter", telegram_id=1)
        await _add_completed_session(user.id, datetime(2026, 1, 1, 10, 0))

        async with async_session_maker() as session:
            await AchievementsService(session).check_and_unlock(
                user.id, date(2026, 1, 1), TZ
            )
            await session.commit()

        async with async_session_maker() as session:
            unlocked_again = await AchievementsService(session).check_and_unlock(
                user.id, date(2026, 1, 1), TZ
            )
            await session.commit()

        assert unlocked_again == []


class TestApiSaveWorkoutLogUnlocksAchievements:
    async def test_first_workout_sends_first_pr_notification(self):
        owner = await _make_user("lifter", telegram_id=1)
        bot = AsyncMock()
        set_bot_instance(bot)

        response = await _save_workout(telegram_id=1)
        assert response.status == 200

        achievement_texts = [
            call.args[1] for call in bot.send_message.await_args_list
            if call.args[1].startswith("🏅")
        ]
        assert achievement_texts == ["🏅 Нове досягнення: Перший рекорд"]
        assert all(
            call.args[0] == owner.telegram_id
            for call in bot.send_message.await_args_list
        )

    async def test_repeated_workout_does_not_repeat_the_notification(self):
        await _make_user("lifter", telegram_id=1)
        await _save_workout(telegram_id=1)  # unlocks FIRST_PR

        bot = AsyncMock()
        set_bot_instance(bot)
        response = await _save_workout(telegram_id=1)

        assert response.status == 200
        achievement_texts = [
            call.args[1] for call in bot.send_message.await_args_list
            if call.args[1].startswith("🏅")
        ]
        assert achievement_texts == []

    async def test_no_bot_instance_still_persists_the_unlock(self):
        owner = await _make_user("lifter", telegram_id=1)
        assert get_bot_instance() is None

        response = await _save_workout(telegram_id=1)
        assert response.status == 200

        async with async_session_maker() as session:
            codes = await UserAchievementRepository(session).get_unlocked_codes(
                owner.id
            )
        assert "FIRST_PR" in codes

    async def test_achievement_check_failure_does_not_fail_the_save(self):
        await _make_user("lifter", telegram_id=1)

        with patch(
            "src.webapp.server._check_and_unlock_achievements",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            response = await _save_workout(telegram_id=1)

        assert response.status == 200


class TestUserAchievementRepositoryUnlockedAtByCode:
    async def test_empty_for_new_user(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            by_code = await UserAchievementRepository(
                session
            ).get_unlocked_at_by_code(user.id)
        assert by_code == {}

    async def test_maps_code_to_its_unlocked_at(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            await UserAchievementRepository(session).unlock(
                user.id, "FIRST_PR", unlocked_at=datetime(2026, 1, 6, 8, 0)
            )
            await session.commit()

        async with async_session_maker() as session:
            by_code = await UserAchievementRepository(
                session
            ).get_unlocked_at_by_code(user.id)
        assert by_code == {"FIRST_PR": datetime(2026, 1, 6, 8, 0)}


def _mock_get_request(path: str, *, telegram_id: int) -> web.Request:
    init_data = build_init_data({"id": telegram_id, "first_name": "Test"})
    return make_mocked_request(
        "GET", path, headers={"Authorization": init_data}
    )


class TestApiGetAchievementsAuthAndValidation:
    async def test_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "GET", "/api/statistics/achievements",
            headers={"Authorization": "garbage"},
        )
        response = await api_get_achievements(request)
        assert response.status == 401

    async def test_unknown_caller_returns_404(self):
        request = _mock_get_request(
            "/api/statistics/achievements", telegram_id=999
        )
        response = await api_get_achievements(request)
        assert response.status == 404


class TestApiGetAchievements:
    async def test_full_catalog_returned_all_locked_by_default(self):
        await _make_user("lifter", telegram_id=1)
        request = _mock_get_request(
            "/api/statistics/achievements", telegram_id=1
        )
        response = await api_get_achievements(request)
        payload = json.loads(response.body)["data"]

        assert response.status == 200
        assert len(payload) == len(ACHIEVEMENTS)
        assert [row["code"] for row in payload] == [a.code for a in ACHIEVEMENTS]
        assert all(row["unlocked"] is False for row in payload)
        assert all(row["unlocked_at"] is None for row in payload)

    async def test_unlocked_achievement_has_shape_and_local_date(self):
        user = await _make_user("lifter", telegram_id=1)
        async with async_session_maker() as session:
            await UserAchievementRepository(session).unlock(
                user.id, "FIRST_PR", unlocked_at=datetime(2026, 1, 6, 8, 0)
            )
            await session.commit()

        request = _mock_get_request(
            "/api/statistics/achievements", telegram_id=1
        )
        response = await api_get_achievements(request)
        payload = json.loads(response.body)["data"]

        first_pr = next(row for row in payload if row["code"] == "FIRST_PR")
        assert first_pr["unlocked"] is True
        assert first_pr["unlocked_at"] == "2026-01-06"
        assert first_pr["title"]
        assert first_pr["description"]

        others = [row for row in payload if row["code"] != "FIRST_PR"]
        assert all(row["unlocked"] is False for row in others)

    async def test_user_param_overrides_caller(self):
        owner = await _make_user("lifter", telegram_id=1)
        await _make_user("trainer", telegram_id=999)
        async with async_session_maker() as session:
            await UserAchievementRepository(session).unlock(owner.id, "FIRST_PR")
            await session.commit()

        request = _mock_get_request(
            "/api/statistics/achievements?user=lifter", telegram_id=999
        )
        response = await api_get_achievements(request)
        payload = json.loads(response.body)["data"]

        first_pr = next(row for row in payload if row["code"] == "FIRST_PR")
        assert first_pr["unlocked"] is True
