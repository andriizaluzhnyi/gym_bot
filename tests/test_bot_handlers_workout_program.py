"""Tests for GYM-28: workout_program.py bot handlers write to the DB
(WorkoutProgramRepository, GYM-27) instead of Google Sheets, Sheets is an
opt-in mirror, and a non-admin never sees the "pick a user" flow.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from src.bot.handlers import workout_program
from src.database.models import Base
from src.database.repository import UserRepository, WorkoutProgramRepository
from src.database.session import async_session_maker, engine
from tests.bot_mocks import make_callback, make_fsm_context, make_message, make_telegram_user


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


def _unique_telegram_id() -> int:
    return uuid.uuid4().int % (2**31)


async def _make_user(username: str | None, telegram_id: int, *, sync_enabled: bool = False):
    async with async_session_maker() as session:
        user, _ = await UserRepository(session).get_or_create(
            telegram_id=telegram_id, first_name="Test", username=username
        )
        user.sync_workout_to_sheets = sync_enabled
        await session.commit()
        return user


CHEST_EXERCISE = {
    "day": 1,
    "muscle_group": "🏋️ Груди",
    "exercise": "Жим лежачи",
    "sets_reps": "3/10",
    "comment": "",
    "created_at": "08.09.2026 12:00",
}


class TestIsAdmin:
    def test_true_for_a_configured_admin(self, monkeypatch):
        monkeypatch.setattr(workout_program.settings, "admin_user_id", 42)
        assert workout_program.is_admin(42) is True

    def test_false_for_anyone_else(self, monkeypatch):
        monkeypatch.setattr(workout_program.settings, "admin_user_id", 42)
        assert workout_program.is_admin(1) is False


class TestStartWorkoutProgramSkipsPickerForNonAdmin:
    async def test_non_admin_goes_straight_to_muscle_group(self, monkeypatch):
        monkeypatch.setattr(workout_program.settings, "admin_user_id", 0)
        telegram_id = _unique_telegram_id()
        await _make_user("caller", telegram_id)
        # Another user exists — a non-admin must still not see a picker.
        await _make_user("someone_else", _unique_telegram_id())

        message = make_message(
            text="💪 Програма тренувань",
            from_user=make_telegram_user(user_id=telegram_id),
        )
        state = make_fsm_context(user_id=telegram_id)

        await workout_program.start_workout_program(message, state)

        assert await state.get_state() == workout_program.WorkoutProgramStates.muscle_group
        data = await state.get_data()
        assert data["selected_user"] is None
        message.answer.assert_awaited_once()
        (text, ), _ = message.answer.call_args
        assert "групу м'язів" in text

    async def test_admin_sees_the_picker_when_other_users_exist(self, monkeypatch):
        telegram_id = _unique_telegram_id()
        monkeypatch.setattr(workout_program.settings, "admin_user_id", telegram_id)
        await _make_user("admin_account", telegram_id)
        await _make_user("client", _unique_telegram_id())

        message = make_message(
            text="💪 Програма тренувань",
            from_user=make_telegram_user(user_id=telegram_id),
        )
        state = make_fsm_context(user_id=telegram_id)

        await workout_program.start_workout_program(message, state)

        assert await state.get_state() == workout_program.WorkoutProgramStates.select_user


class TestViewProgramsSkipsPickerForNonAdmin:
    async def test_non_admin_goes_straight_to_muscle_filter(self, monkeypatch):
        monkeypatch.setattr(workout_program.settings, "admin_user_id", 0)
        telegram_id = _unique_telegram_id()
        await _make_user("caller", telegram_id)
        await _make_user("someone_else", _unique_telegram_id())

        message = make_message(
            text="📋 Переглянути програми",
            from_user=make_telegram_user(user_id=telegram_id),
        )
        state = make_fsm_context(user_id=telegram_id)

        await workout_program.view_programs(message, state)

        assert await state.get_state() == workout_program.WorkoutProgramStates.view_filter_muscle
        data = await state.get_data()
        assert data["selected_user"] is None


class TestProgramFinishSavesToDb:
    async def test_writes_exercises_to_the_db(self):
        telegram_id = _unique_telegram_id()
        owner = await _make_user("lifter", telegram_id, sync_enabled=False)

        state = make_fsm_context(user_id=telegram_id)
        await state.update_data(
            exercises=[CHEST_EXERCISE], day_number=1, selected_user=None,
        )
        callback = make_callback(
            data="program:finish", from_user=make_telegram_user(user_id=telegram_id),
        )

        with patch("src.bot.handlers.workout_program.GoogleSheetsService") as mock_sheets_cls:
            await workout_program.process_program_action(callback, state)
            mock_sheets_cls.assert_not_called()

        async with async_session_maker() as session:
            program = await WorkoutProgramRepository(session).get_program(owner.id)
        assert len(program) == 1
        assert program[0]["exercise"] == "Жим лежачи"

        callback.message.edit_text.assert_awaited_once()
        (summary, ), _ = callback.message.edit_text.call_args
        assert "Sheets" not in summary
        assert await state.get_state() is None

    async def test_mirrors_to_sheets_when_owner_opted_in(self):
        telegram_id = _unique_telegram_id()
        await _make_user("lifter", telegram_id, sync_enabled=True)

        state = make_fsm_context(user_id=telegram_id)
        await state.update_data(
            exercises=[CHEST_EXERCISE], day_number=1, selected_user=None,
        )
        callback = make_callback(
            data="program:finish", from_user=make_telegram_user(user_id=telegram_id),
        )

        with patch("src.bot.handlers.workout_program.GoogleSheetsService") as mock_sheets_cls:
            instance = mock_sheets_cls.return_value
            instance.add_workout_program = AsyncMock(return_value=True)
            await workout_program.process_program_action(callback, state)
            instance.add_workout_program.assert_awaited_once_with(
                [CHEST_EXERCISE], user_name="lifter"
            )

        callback.message.edit_text.assert_awaited_once()
        (summary, ), _ = callback.message.edit_text.call_args
        assert "Продубльовано в Google Sheets" in summary

    async def test_sheets_failure_does_not_block_the_db_save(self):
        telegram_id = _unique_telegram_id()
        owner = await _make_user("lifter", telegram_id, sync_enabled=True)

        state = make_fsm_context(user_id=telegram_id)
        await state.update_data(
            exercises=[CHEST_EXERCISE], day_number=1, selected_user=None,
        )
        callback = make_callback(
            data="program:finish", from_user=make_telegram_user(user_id=telegram_id),
        )

        with patch("src.bot.handlers.workout_program.GoogleSheetsService") as mock_sheets_cls:
            instance = mock_sheets_cls.return_value
            instance.add_workout_program = AsyncMock(side_effect=RuntimeError("boom"))
            await workout_program.process_program_action(callback, state)

        async with async_session_maker() as session:
            program = await WorkoutProgramRepository(session).get_program(owner.id)
        assert len(program) == 1

        callback.message.edit_text.assert_awaited_once()
        (summary, ), _ = callback.message.edit_text.call_args
        assert "Не вдалося продублювати" in summary

    async def test_shows_admin_keyboard_for_an_admin(self, monkeypatch):
        telegram_id = _unique_telegram_id()
        monkeypatch.setattr(workout_program.settings, "admin_user_id", telegram_id)
        await _make_user("admin_account", telegram_id)

        state = make_fsm_context(user_id=telegram_id)
        await state.update_data(
            exercises=[CHEST_EXERCISE], day_number=1, selected_user=None,
        )
        callback = make_callback(
            data="program:finish", from_user=make_telegram_user(user_id=telegram_id),
        )

        with patch("src.bot.handlers.workout_program.GoogleSheetsService"):
            await workout_program.process_program_action(callback, state)

        callback.message.answer.assert_awaited_once()
        _, kwargs = callback.message.answer.call_args
        keyboard = kwargs["reply_markup"]
        texts = [btn.text for row in keyboard.keyboard for btn in row]
        assert "💪 Програма тренувань" in texts

    async def test_shows_main_keyboard_for_a_non_admin(self, monkeypatch):
        monkeypatch.setattr(workout_program.settings, "admin_user_id", 0)
        telegram_id = _unique_telegram_id()
        await _make_user("lifter", telegram_id)

        state = make_fsm_context(user_id=telegram_id)
        await state.update_data(
            exercises=[CHEST_EXERCISE], day_number=1, selected_user=None,
        )
        callback = make_callback(
            data="program:finish", from_user=make_telegram_user(user_id=telegram_id),
        )

        with patch("src.bot.handlers.workout_program.GoogleSheetsService"):
            await workout_program.process_program_action(callback, state)

        callback.message.answer.assert_awaited_once()
        _, kwargs = callback.message.answer.call_args
        keyboard = kwargs["reply_markup"]
        texts = [btn.text for row in keyboard.keyboard for btn in row]
        assert "💪 Програма тренувань" not in texts
        assert "👤 Профіль" in texts

    async def test_admin_saves_to_the_picked_users_account_not_their_own(self, monkeypatch):
        admin_telegram_id = _unique_telegram_id()
        monkeypatch.setattr(workout_program.settings, "admin_user_id", admin_telegram_id)
        await _make_user("admin_account", admin_telegram_id)
        client = await _make_user("client", _unique_telegram_id())

        state = make_fsm_context(user_id=admin_telegram_id)
        await state.update_data(
            exercises=[CHEST_EXERCISE], day_number=1, selected_user="client",
        )
        callback = make_callback(
            data="program:finish",
            from_user=make_telegram_user(user_id=admin_telegram_id),
        )

        with patch("src.bot.handlers.workout_program.GoogleSheetsService"):
            await workout_program.process_program_action(callback, state)

        async with async_session_maker() as session:
            client_program = await WorkoutProgramRepository(session).get_program(client.id)
        assert len(client_program) == 1


class TestGetLastDayForMuscleUsesDb:
    async def test_reflects_an_existing_program(self, monkeypatch):
        monkeypatch.setattr(workout_program.settings, "admin_user_id", 0)
        telegram_id = _unique_telegram_id()
        owner = await _make_user("lifter", telegram_id)

        async with async_session_maker() as session:
            await WorkoutProgramRepository(session).add_exercises(
                owner.id, 3, [CHEST_EXERCISE]
            )
            await session.commit()

        state = make_fsm_context(user_id=telegram_id)
        await state.update_data(selected_user=None)
        callback = make_callback(
            data="muscle:🏋️ Груди", from_user=make_telegram_user(user_id=telegram_id),
        )

        await workout_program.process_muscle_group(callback, state)

        callback.message.edit_text.assert_awaited_once()
        _, kwargs = callback.message.edit_text.call_args
        keyboard = kwargs["reply_markup"]
        buttons = [b for row in keyboard.inline_keyboard for b in row]
        assert any(b.callback_data == "day:continue:3" for b in buttons)


class TestProcessCommentNormalizesSetsReps:
    """GYM-46: process_comment normalizes a parseable sets_reps value
    (single or comma-separated blocks) before storing it, but leaves free
    text that doesn't parse this way exactly as the user typed it.
    """

    async def _run(self, *, current_sets: str, current_reps: str = ""):
        telegram_id = _unique_telegram_id()
        state = make_fsm_context(user_id=telegram_id)
        await state.update_data(
            current_sets=current_sets,
            current_reps=current_reps,
            current_muscle_group="🏋️ Груди",
            current_exercise="Жим лежачи",
            day_number=1,
            exercises=[],
        )
        message = make_message(
            text="-", from_user=make_telegram_user(user_id=telegram_id)
        )

        await workout_program.process_comment(message, state)

        data = await state.get_data()
        return data["exercises"][-1]["sets_reps"]

    async def test_untidy_combined_input_is_normalized(self):
        stored = await self._run(current_sets="2/12,4x6")
        assert stored == "2/12, 4/6"

    async def test_already_canonical_input_is_unchanged(self):
        stored = await self._run(current_sets="3/10")
        assert stored == "3/10"

    async def test_two_step_sets_then_reps_flow_still_combines(self):
        # The keyboard-driven path: sets collected in one step, reps in
        # the next, joined by `combine_sets_reps` before normalization.
        stored = await self._run(current_sets="4", current_reps="8")
        assert stored == "4/8"

    async def test_unparsed_free_text_is_kept_as_is(self):
        stored = await self._run(current_sets="до відмови")
        assert stored == "до відмови"
