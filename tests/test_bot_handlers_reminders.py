"""Tests for GYM-33: `/reminders` (src/bot/handlers/group_reminders.py) —
the group's reminder-settings panel and its `grem:*` callback buttons.
"""

from unittest.mock import MagicMock

import pytest

from src.bot.handlers import group_reminders
from src.database.models import Base
from src.database.repository import GroupChatRepository
from src.database.session import async_session_maker, engine
from tests.bot_mocks import make_callback, make_chat, make_chat_member, make_message


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
        assert any(cd.startswith("grem:settime:nutrition:") for cd in all_callback_data)
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

    async def test_time_outside_the_allowed_chips_is_rejected(self):
        await _register_group(chat_id=-100)
        callback = _admin_callback("grem:settime:nutrition:03:33")

        await group_reminders.process_reminders_callback(callback)

        callback.answer.assert_awaited_once()
        _, kwargs = callback.answer.call_args
        assert kwargs.get("show_alert") is True

        group = await _get_group(-100)
        assert group.nutrition_time == "20:00"  # unchanged


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
