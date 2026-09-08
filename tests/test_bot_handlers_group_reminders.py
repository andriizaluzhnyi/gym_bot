"""Tests for GYM-32: src/bot/handlers/group_reminders.py — registering/
deregistering a GroupChat on the bot's `my_chat_member` update, plus the
`GroupChatRepository` methods it (and GYM-33/34) rely on.
"""

import pytest

from aiogram import Dispatcher

from src.bot.handlers import group_reminders, setup_routers
from src.database.models import Base
from src.database.repository import GroupChatRepository
from src.database.session import async_session_maker, engine
from tests.bot_mocks import make_chat, make_chat_member_updated, make_telegram_user


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _get_group(chat_id: int):
    async with async_session_maker() as session:
        return await GroupChatRepository(session).get_by_chat_id(chat_id)


class TestOnBotAddedToGroup:
    async def test_creates_an_active_group_chat_row(self):
        event = make_chat_member_updated(
            chat=make_chat(chat_id=-100, chat_type="group"),
            from_user=make_telegram_user(user_id=42),
        )

        await group_reminders.on_bot_added_to_group(event)

        group = await _get_group(-100)
        assert group is not None
        assert group.is_active is True
        assert group.added_by_telegram_id == 42

    async def test_default_reminder_settings(self):
        event = make_chat_member_updated(chat=make_chat(chat_id=-100, chat_type="group"))
        await group_reminders.on_bot_added_to_group(event)

        group = await _get_group(-100)
        assert group.remind_nutrition is True
        assert group.nutrition_time == "20:00"
        assert group.remind_measurements is True
        assert group.measurements_weekday == 0
        assert group.measurements_time == "09:00"
        assert group.remind_photos is False
        assert group.photos_day_of_month == 1
        assert group.photos_time == "09:00"

    async def test_sends_welcome_message(self):
        event = make_chat_member_updated(chat=make_chat(chat_id=-100, chat_type="group"))
        await group_reminders.on_bot_added_to_group(event)

        event.answer.assert_awaited_once()
        (text,), _ = event.answer.call_args
        assert "20:00" in text
        assert "09:00" in text
        assert "/reminders" in text

    async def test_reactivates_and_preserves_settings_on_rejoin(self):
        # First join, customize a setting, then leave.
        event = make_chat_member_updated(chat=make_chat(chat_id=-100, chat_type="group"))
        await group_reminders.on_bot_added_to_group(event)
        async with async_session_maker() as session:
            repo = GroupChatRepository(session)
            await repo.update_settings(-100, nutrition_time="18:30")
            await session.commit()
        await group_reminders.on_bot_removed_from_group(event)

        # Re-join.
        rejoin_event = make_chat_member_updated(chat=make_chat(chat_id=-100, chat_type="group"))
        await group_reminders.on_bot_added_to_group(rejoin_event)

        group = await _get_group(-100)
        assert group.is_active is True
        assert group.nutrition_time == "18:30"  # preserved, not reset to default

    async def test_refreshes_title_on_rejoin(self):
        event = make_chat_member_updated(
            chat=make_chat(chat_id=-100, chat_type="group")
        )
        event.chat.title = "Old Title"
        await group_reminders.on_bot_added_to_group(event)
        await group_reminders.on_bot_removed_from_group(event)

        rejoin_event = make_chat_member_updated(chat=make_chat(chat_id=-100, chat_type="group"))
        rejoin_event.chat.title = "New Title"
        await group_reminders.on_bot_added_to_group(rejoin_event)

        group = await _get_group(-100)
        assert group.title == "New Title"

    async def test_welcome_message_failure_does_not_prevent_registration(self):
        event = make_chat_member_updated(chat=make_chat(chat_id=-100, chat_type="group"))
        event.answer.side_effect = RuntimeError("bot was blocked")

        await group_reminders.on_bot_added_to_group(event)

        group = await _get_group(-100)
        assert group is not None
        assert group.is_active is True


class TestOnBotRemovedFromGroup:
    async def test_deactivates_existing_group(self):
        join_event = make_chat_member_updated(chat=make_chat(chat_id=-100, chat_type="group"))
        await group_reminders.on_bot_added_to_group(join_event)

        leave_event = make_chat_member_updated(
            chat=make_chat(chat_id=-100, chat_type="group"),
            old_status="member", new_status="left",
        )
        await group_reminders.on_bot_removed_from_group(leave_event)

        group = await _get_group(-100)
        assert group.is_active is False

    async def test_kicked_also_deactivates(self):
        join_event = make_chat_member_updated(chat=make_chat(chat_id=-100, chat_type="group"))
        await group_reminders.on_bot_added_to_group(join_event)

        leave_event = make_chat_member_updated(
            chat=make_chat(chat_id=-100, chat_type="group"),
            old_status="member", new_status="kicked",
        )
        await group_reminders.on_bot_removed_from_group(leave_event)

        group = await _get_group(-100)
        assert group.is_active is False

    async def test_no_op_when_group_was_never_registered(self):
        leave_event = make_chat_member_updated(
            chat=make_chat(chat_id=-999, chat_type="group"),
            old_status="member", new_status="left",
        )
        # Should not raise.
        await group_reminders.on_bot_removed_from_group(leave_event)
        assert await _get_group(-999) is None


class TestFilterWiring:
    """Exercised through the router's own observer
    (``group_reminders.router.my_chat_member.trigger``), which runs the
    real registered filters (``ChatMemberUpdatedFilter`` + ``F.chat.type``)
    before invoking a handler — the same check
    ``Dispatcher.feed_update`` performs, without needing to construct a
    full ``aiogram.types.Update`` (a pydantic model requiring exactly one
    event field set, awkward to build from a mock).
    """

    async def test_join_transition_routes_to_the_join_handler(self):
        event = make_chat_member_updated(chat=make_chat(chat_id=-100, chat_type="supergroup"))
        await group_reminders.router.my_chat_member.trigger(event)

        group = await _get_group(-100)
        assert group is not None
        assert group.is_active is True

    async def test_leave_transition_routes_to_the_leave_handler(self):
        join_event = make_chat_member_updated(chat=make_chat(chat_id=-100, chat_type="group"))
        await group_reminders.router.my_chat_member.trigger(join_event)

        leave_event = make_chat_member_updated(
            chat=make_chat(chat_id=-100, chat_type="group"),
            old_status="member", new_status="left",
        )
        await group_reminders.router.my_chat_member.trigger(leave_event)

        group = await _get_group(-100)
        assert group.is_active is False

    async def test_private_chat_matches_neither_handler(self):
        event = make_chat_member_updated(chat=make_chat(chat_id=555, chat_type="private"))
        await group_reminders.router.my_chat_member.trigger(event)

        assert await _get_group(555) is None

    def test_my_chat_member_is_a_used_update_type(self):
        """AC: dp.resolve_used_update_types() must list `my_chat_member`
        once this router is registered, so aiogram's polling actually
        subscribes to it (it's opt-in, not part of the default set).
        """
        dp = Dispatcher()
        dp.include_router(setup_routers())
        assert "my_chat_member" in dp.resolve_used_update_types()
