"""Tests for GYM-33: `/reminders` (src/bot/handlers/group_reminders.py) —
the group's reminder-settings panel and its `grem:*` callback buttons.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.handlers import group_reminders
from src.database.models import Base
from src.database.repository import GroupChatRepository
from src.database.session import async_session_maker, engine
from tests.bot_mocks import (
    make_callback,
    make_chat,
    make_chat_member,
    make_fsm_context,
    make_message,
    make_telegram_user,
)


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _register_group(chat_id: int = -100, added_by: int = 1):
    async with async_session_maker() as session:
        group = await GroupChatRepository(session).upsert_active(
            chat_id=chat_id, title="Test Group", added_by_telegram_id=added_by
        )
        await session.commit()
        return group


async def _get_group(chat_id: int = -100):
    async with async_session_maker() as session:
        return await GroupChatRepository(session).get_by_chat_id(chat_id)


def _admin_callback(data: str, *, chat_id: int = -100, chat_type: str = "group"):
    """A callback from an admin of the group — `get_chat_member` resolves
    to "administrator" by default.
    """
    message = make_message(chat=make_chat(chat_id=chat_id, chat_type=chat_type))
    callback = make_callback(data=data, message=message)
    callback.bot.get_chat_member.return_value = make_chat_member(status="administrator")  # type: ignore[union-attr]
    return callback


def _member_callback(data: str, *, chat_id: int = -100, chat_type: str = "group"):
    """A callback from a plain (non-admin) member of the group."""
    message = make_message(chat=make_chat(chat_id=chat_id, chat_type=chat_type))
    callback = make_callback(data=data, message=message)
    callback.bot.get_chat_member.return_value = make_chat_member(status="member")  # type: ignore[union-attr]
    return callback


class TestCmdReminders:
    async def test_private_chat_gets_a_hint_instead_of_the_panel(self):
        message = make_message(chat=make_chat(chat_type="private"))
        await group_reminders.cmd_reminders(message)

        message.answer.assert_awaited_once()
        (text,), kwargs = message.answer.call_args
        assert "групу" in text.lower()
        assert "reply_markup" not in kwargs

    async def test_unregistered_group_gets_an_explanatory_message(self):
        message = make_message(chat=make_chat(chat_id=-999, chat_type="group"))
        await group_reminders.cmd_reminders(message)

        message.answer.assert_awaited_once()
        (text,), kwargs = message.answer.call_args
        assert "reply_markup" not in kwargs

    async def test_registered_group_gets_the_panel(self):
        await _register_group(chat_id=-100)
        message = make_message(chat=make_chat(chat_id=-100, chat_type="group"))

        await group_reminders.cmd_reminders(message)

        message.answer.assert_awaited_once()
        _, kwargs = message.answer.call_args
        keyboard = kwargs["reply_markup"]
        # 3 reminder types, each a [toggle, time] row.
        assert len(keyboard.inline_keyboard) == 3
        for row in keyboard.inline_keyboard:
            assert len(row) == 2
            assert row[0].callback_data.startswith("grem:toggle:")
            assert row[1].callback_data.startswith("grem:time:")

    async def test_inactive_group_is_reactivated(self):
        # The bot is evidently in the group (it received the command), so
        # a stale is_active=False must not keep the scheduler skipping it.
        await _register_group(chat_id=-100)
        async with async_session_maker() as session:
            await GroupChatRepository(session).deactivate(-100)
            await session.commit()

        message = make_message(chat=make_chat(chat_id=-100, chat_type="group"))
        await group_reminders.cmd_reminders(message)

        assert (await _get_group(-100)).is_active is True
        _, kwargs = message.answer.call_args
        assert "reply_markup" in kwargs

    async def test_panel_reflects_current_state(self):
        await _register_group(chat_id=-100)
        async with async_session_maker() as session:
            await GroupChatRepository(session).update_settings(-100, remind_photos=True)
            await session.commit()

        message = make_message(chat=make_chat(chat_id=-100, chat_type="group"))
        await group_reminders.cmd_reminders(message)

        _, kwargs = message.answer.call_args
        keyboard = kwargs["reply_markup"]
        button_texts = [row[0].text for row in keyboard.inline_keyboard]
        assert any("✅" in t and "Харчування" in t for t in button_texts)
        assert any("✅" in t and "Фото" in t for t in button_texts)


class TestNonAdminCannotChangeSettings:
    async def test_toggle_is_rejected_with_an_alert(self):
        await _register_group(chat_id=-100)
        callback = _member_callback("grem:toggle:nutrition")

        await group_reminders.process_reminders_callback(callback)

        callback.answer.assert_awaited_once()
        _, kwargs = callback.answer.call_args
        assert kwargs.get("show_alert") is True
        assert "адмін" in callback.answer.call_args.args[0].lower()

        group = await _get_group(-100)
        assert group.remind_nutrition is True  # unchanged (default)

    async def test_settime_is_rejected(self):
        await _register_group(chat_id=-100)
        callback = _member_callback("grem:settime:nutrition:07:00")

        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.nutrition_time == "20:00"  # unchanged (default)

    async def test_viewing_the_panel_is_open_to_everyone(self):
        # /reminders itself (cmd_reminders) has no admin check at all —
        # only the callback handler that changes settings does.
        await _register_group(chat_id=-100)
        message = make_message(chat=make_chat(chat_id=-100, chat_type="group"))
        await group_reminders.cmd_reminders(message)
        message.answer.assert_awaited_once()


class TestToggle:
    async def test_toggle_flips_nutrition(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:toggle:nutrition")

        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.remind_nutrition is False

        # Toggling again flips it back.
        callback2 = _admin_callback("grem:toggle:nutrition")
        await group_reminders.process_reminders_callback(callback2)
        group = await _get_group(-100)
        assert group.remind_nutrition is True

    async def test_toggle_flips_measurements(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:toggle:measurements")
        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.remind_measurements is False

    async def test_toggle_flips_photos(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:toggle:photos")
        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.remind_photos is True  # default False -> True

    async def test_toggle_redraws_the_panel_in_place(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:toggle:nutrition")

        await group_reminders.process_reminders_callback(callback)

        callback.message.edit_reply_markup.assert_awaited_once()
        callback.answer.assert_awaited_once_with()


class TestTimeSubmenu:
    async def test_time_action_opens_the_submenu_without_changing_settings(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:time:nutrition")

        await group_reminders.process_reminders_callback(callback)

        callback.message.edit_reply_markup.assert_awaited_once()
        _, kwargs = callback.message.edit_reply_markup.call_args
        keyboard = kwargs["reply_markup"]
        all_callback_data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert any(cd.startswith("grem:addtime:nutrition:") for cd in all_callback_data)
        assert "grem:deltime:nutrition:20:00" in all_callback_data
        assert "grem:custom:nutrition" in all_callback_data
        assert "grem:back" in all_callback_data

        group = await _get_group(-100)
        assert group.nutrition_time == "20:00"  # unchanged

    async def test_measurements_submenu_includes_a_weekday_row(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:time:measurements")
        await group_reminders.process_reminders_callback(callback)

        _, kwargs = callback.message.edit_reply_markup.call_args
        keyboard = kwargs["reply_markup"]
        all_callback_data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert any(cd.startswith("grem:setweekday:") for cd in all_callback_data)

    async def test_photos_submenu_includes_a_day_of_month_row(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:time:photos")
        await group_reminders.process_reminders_callback(callback)

        _, kwargs = callback.message.edit_reply_markup.call_args
        keyboard = kwargs["reply_markup"]
        all_callback_data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert "grem:setday:1" in all_callback_data
        assert "grem:setday:15" in all_callback_data


class TestSetTime:
    async def test_valid_time_is_applied(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:settime:nutrition:07:00")
        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.nutrition_time == "07:00"

    async def test_applies_to_the_correct_reminder_type(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:settime:measurements:18:00")
        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.measurements_time == "18:00"
        assert group.nutrition_time == "20:00"  # untouched

    async def test_any_valid_time_is_accepted(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:settime:nutrition:03:33")
        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.nutrition_time == "03:33"

    async def test_inactive_group_is_reactivated(self):
        # Changing settings from the panel proves the bot is in the group —
        # a stale is_active=False must not keep the scheduler skipping it.
        await _register_group(chat_id=-100)
        async with async_session_maker() as session:
            await GroupChatRepository(session).deactivate(-100)
            await session.commit()

        callback = _admin_callback("grem:addtime:nutrition:23:00")
        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.is_active is True
        assert group.nutrition_time == "20:00,23:00"

    async def test_invalid_time_is_rejected(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:settime:nutrition:25:99")

        await group_reminders.process_reminders_callback(callback)

        callback.answer.assert_awaited_once()
        _, kwargs = callback.answer.call_args
        assert kwargs.get("show_alert") is True

        group = await _get_group(-100)
        assert group.nutrition_time == "20:00"  # unchanged


class TestAddAndDeleteTimes:
    async def test_addtime_appends_a_slot_and_stays_in_the_submenu(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:addtime:nutrition:12:00")
        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.nutrition_time == "12:00,20:00"
        _, kwargs = callback.message.edit_reply_markup.call_args
        all_callback_data = [
            b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row
        ]
        assert "grem:deltime:nutrition:12:00" in all_callback_data
        assert "grem:back" in all_callback_data  # still the submenu

    async def test_addtime_is_idempotent(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:addtime:nutrition:20:00")
        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.nutrition_time == "20:00"

    async def test_deltime_removes_a_slot(self):
        await _register_group(chat_id=-100)
        async with async_session_maker() as session:
            await GroupChatRepository(session).update_settings(
                -100, nutrition_time="08:00,20:00"
            )
            await session.commit()

        callback = _admin_callback("grem:deltime:nutrition:08:00")
        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.nutrition_time == "20:00"

    async def test_last_slot_cannot_be_deleted(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:deltime:nutrition:20:00")
        await group_reminders.process_reminders_callback(callback)

        _, kwargs = callback.answer.call_args
        assert kwargs.get("show_alert") is True
        group = await _get_group(-100)
        assert group.nutrition_time == "20:00"

    async def test_adding_a_past_time_does_not_fire_it_today(self, monkeypatch):
        """Adding 10:00 at 15:00 must not send a "late" 10:00 reminder on
        the next tick — the schedule change applies from now on."""
        from datetime import datetime

        from src.services.group_reminders import ReminderKind, due_reminders

        now = datetime(2026, 6, 15, 15, 0)
        monkeypatch.setattr(group_reminders, "to_local_now", lambda tz_name: now)
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:addtime:nutrition:10:00")
        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert ReminderKind.NUTRITION not in due_reminders(group, now)
        assert ReminderKind.NUTRITION in due_reminders(group, datetime(2026, 6, 15, 20, 0))


class TestTimeInTheCurrentMinute:
    async def test_adding_the_current_minute_fires_on_the_next_tick(self, monkeypatch):
        """Trainer adds 15:00 at 15:00:20 — must fire now, not tomorrow."""
        from datetime import datetime

        from src.services.group_reminders import ReminderKind, due_reminders

        now = datetime(2026, 6, 15, 15, 0, 20)
        monkeypatch.setattr(group_reminders, "to_local_now", lambda tz_name: now)
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:addtime:nutrition:15:00")
        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert ReminderKind.NUTRITION in due_reminders(group, datetime(2026, 6, 15, 15, 1))


class TestCustomTimeInput:
    async def _start(self, state, reminder_type="nutrition"):
        callback = _admin_callback(f"grem:custom:{reminder_type}")
        callback.from_user.mention_html.return_value = "<a>Trainer</a>"
        await group_reminders.process_reminders_custom_time(callback, state)
        return callback

    def _reply(self, text, user_id=1):
        return make_message(
            text=text,
            chat=make_chat(chat_id=-100, chat_type="group"),
            from_user=make_telegram_user(user_id=user_id),
        )

    async def test_prompt_uses_force_reply_and_sets_state(self):
        await _register_group(chat_id=-100)
        state = make_fsm_context(chat_id=-100)
        callback = await self._start(state)

        callback.message.answer.assert_awaited_once()
        _, kwargs = callback.message.answer.call_args
        assert kwargs["reply_markup"].force_reply is True
        assert await state.get_state() == group_reminders.GroupReminderStates.waiting_times.state

    async def test_reply_adds_several_custom_times(self):
        await _register_group(chat_id=-100)
        state = make_fsm_context(chat_id=-100)
        await self._start(state)

        message = self._reply("8:15, 13:00 21.45")
        message.bot.get_chat_member = AsyncMock(
            return_value=make_chat_member(status="administrator")
        )
        await group_reminders.process_reminders_times_input(message, state)

        group = await _get_group(-100)
        assert group.nutrition_time == "08:15,13:00,20:00,21:45"
        assert await state.get_state() is None
        (text,), _ = message.answer.call_args
        assert "08:15" in text

    async def test_reply_reactivates_inactive_group(self):
        await _register_group(chat_id=-100)
        async with async_session_maker() as session:
            await GroupChatRepository(session).deactivate(-100)
            await session.commit()
        state = make_fsm_context(chat_id=-100)
        await self._start(state)

        message = self._reply("23:00")
        message.bot.get_chat_member = AsyncMock(
            return_value=make_chat_member(status="administrator")
        )
        await group_reminders.process_reminders_times_input(message, state)

        group = await _get_group(-100)
        assert group.is_active is True
        assert group.nutrition_time == "20:00,23:00"

    async def test_invalid_reply_keeps_waiting(self):
        await _register_group(chat_id=-100)
        state = make_fsm_context(chat_id=-100)
        await self._start(state)

        message = self._reply("about eight")
        message.bot.get_chat_member = AsyncMock(
            return_value=make_chat_member(status="administrator")
        )
        await group_reminders.process_reminders_times_input(message, state)

        group = await _get_group(-100)
        assert group.nutrition_time == "20:00"
        assert await state.get_state() is not None

    async def test_dash_cancels(self):
        await _register_group(chat_id=-100)
        state = make_fsm_context(chat_id=-100)
        await self._start(state)

        message = self._reply("-")
        await group_reminders.process_reminders_times_input(message, state)

        assert await state.get_state() is None
        group = await _get_group(-100)
        assert group.nutrition_time == "20:00"

    async def test_too_many_times_is_rejected(self):
        await _register_group(chat_id=-100)
        state = make_fsm_context(chat_id=-100)
        await self._start(state)

        many = ", ".join(f"{h:02d}:30" for h in range(24))  # 24 + existing 20:00
        message = self._reply(many)
        message.bot.get_chat_member = AsyncMock(
            return_value=make_chat_member(status="administrator")
        )
        await group_reminders.process_reminders_times_input(message, state)

        group = await _get_group(-100)
        assert group.nutrition_time == "20:00"

    async def test_non_admin_cannot_open_custom_input(self):
        await _register_group(chat_id=-100)
        state = make_fsm_context(chat_id=-100)
        callback = _member_callback("grem:custom:nutrition")

        await group_reminders.process_reminders_custom_time(callback, state)

        _, kwargs = callback.answer.call_args
        assert kwargs.get("show_alert") is True
        assert await state.get_state() is None


class TestTrainerAccess:
    async def test_bot_admin_can_change_settings_without_being_group_admin(
        self, monkeypatch
    ):
        monkeypatch.setattr(group_reminders.settings, "admin_user_id", 1)
        await _register_group(chat_id=-100)
        callback = _member_callback("grem:toggle:nutrition")  # from_user.id == 1

        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.remind_nutrition is False
        callback.bot.get_chat_member.assert_not_awaited()


class TestSetWeekday:
    async def test_valid_weekday_is_applied(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:setweekday:3")
        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.measurements_weekday == 3

    async def test_out_of_range_weekday_is_rejected(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:setweekday:9")

        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.measurements_weekday == 0  # unchanged (default Monday)


class TestSetDay:
    async def test_valid_day_is_applied(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:setday:15")
        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.photos_day_of_month == 15

    async def test_day_outside_the_allowed_chips_is_rejected(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:setday:20")

        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.photos_day_of_month == 1  # unchanged (default)


class TestBack:
    async def test_back_redraws_the_main_panel(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:back")

        await group_reminders.process_reminders_callback(callback)

        callback.message.edit_reply_markup.assert_awaited_once()
        _, kwargs = callback.message.edit_reply_markup.call_args
        keyboard = kwargs["reply_markup"]
        assert len(keyboard.inline_keyboard) == 3  # the main panel, not a submenu


class TestEdgeCases:
    async def test_private_chat_callback_is_ignored(self):
        message = make_message(chat=make_chat(chat_type="private"))
        callback = make_callback(data="grem:toggle:nutrition", message=message)

        await group_reminders.process_reminders_callback(callback)

        callback.answer.assert_awaited_once_with()
        callback.bot.get_chat_member.assert_not_awaited()

    async def test_unregistered_group_is_a_no_op(self):
        callback = _admin_callback("grem:toggle:nutrition", chat_id=-999)
        # No _register_group call — group doesn't exist.
        await group_reminders.process_reminders_callback(callback)
        callback.answer.assert_awaited_once_with()

    async def test_malformed_callback_data_does_not_crash(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:setweekday:not-a-number")

        # Should not raise.
        await group_reminders.process_reminders_callback(callback)
        callback.answer.assert_awaited_once()

    async def test_unknown_action_is_ignored(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:frobnicate")

        await group_reminders.process_reminders_callback(callback)

        callback.answer.assert_awaited_once_with()
        group = await _get_group(-100)
        assert group.remind_nutrition is True  # untouched


class TestIsGroupAdmin:
    async def test_creator_counts_as_admin(self):
        callback = make_callback(
            data="grem:toggle:nutrition",
            message=make_message(chat=make_chat(chat_id=-100, chat_type="group")),
        )
        callback.bot.get_chat_member.return_value = make_chat_member(status="creator")
        await _register_group(chat_id=-100)

        await group_reminders.process_reminders_callback(callback)

        group = await _get_group(-100)
        assert group.remind_nutrition is False  # the toggle went through

    async def test_get_chat_member_failure_denies_access(self):
        await _register_group(chat_id=-100)
        message = make_message(chat=make_chat(chat_id=-100, chat_type="group"))
        callback = make_callback(data="grem:toggle:nutrition", message=message)
        callback.bot.get_chat_member.side_effect = RuntimeError("network error")

        await group_reminders.process_reminders_callback(callback)

        callback.answer.assert_awaited_once()
        _, kwargs = callback.answer.call_args
        assert kwargs.get("show_alert") is True
        group = await _get_group(-100)
        assert group.remind_nutrition is True  # unchanged


class TestUsedByFromUser:
    async def test_missing_from_user_is_a_no_op(self):
        callback = _admin_callback("grem:toggle:nutrition")
        callback.from_user = None

        await group_reminders.process_reminders_callback(callback)

        callback.answer.assert_awaited_once_with()
        callback.bot.get_chat_member.assert_not_awaited()


class TestFilterWiring:
    """Exercised through the router's own observers
    (``group_reminders.router.message``/``.callback_query``), which run
    the real registered filters (``Command("reminders")``,
    ``F.data.startswith("grem:")``) before invoking a handler — same
    approach as ``tests/test_bot_handlers_group_reminders.py``'s
    ``TestFilterWiring`` for GYM-32's `my_chat_member` filters.
    """

    async def test_slash_reminders_routes_to_cmd_reminders(self):
        message = make_message(
            text="/reminders", chat=make_chat(chat_id=-100, chat_type="group")
        )
        await group_reminders.router.message.trigger(message, bot=MagicMock())
        message.answer.assert_awaited_once()

    async def test_unrelated_text_does_not_match(self):
        message = make_message(
            text="hello", chat=make_chat(chat_id=-100, chat_type="group")
        )
        await group_reminders.router.message.trigger(message, bot=MagicMock())
        message.answer.assert_not_awaited()

    async def test_grem_prefixed_callback_data_routes_to_the_handler(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:toggle:nutrition")
        await group_reminders.router.callback_query.trigger(callback)
        callback.answer.assert_awaited_once()

    async def test_other_prefixes_do_not_match_this_router(self):
        """AC: the `grem:` prefix must not collide with `program:`/`edit:`
        (workout_program.py's own callback_data prefixes)."""
        callback = make_callback(
            data="program:something",
            message=make_message(chat=make_chat(chat_id=-100, chat_type="group")),
        )
        await group_reminders.router.callback_query.trigger(callback)
        callback.answer.assert_not_awaited()
