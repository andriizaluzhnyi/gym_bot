"""Tests for GYM-34: src/services/group_reminders.py.

``due_reminders``/``_is_due`` are pure (no DB/network) — tested directly
against a plain, unsaved ``GroupChat`` instance and an arbitrary
``now_local``. ``GroupReminderService`` (the sending half) is tested
separately below with a mocked ``Bot`` and a real (SQLite) DB.
"""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramNotFound

from src.database.models import Base, GroupChat
from src.database.repository import GroupChatRepository
from src.database.session import async_session_maker, engine
from src.services.group_reminders import GroupReminderService, ReminderKind, due_reminders


def _make_group(**overrides) -> GroupChat:
    """A plain, unsaved GroupChat — every field explicit so a test never
    silently relies on a column default that could change.
    """
    defaults = {
        "chat_id": -100,
        "title": "Test Group",
        "is_active": True,
        "added_by_telegram_id": 1,
        "remind_nutrition": True,
        "nutrition_time": "20:00",
        "remind_measurements": True,
        "measurements_weekday": 0,  # Monday
        "measurements_time": "09:00",
        "remind_photos": True,
        "photos_day_of_month": 15,
        "photos_time": "09:00",
        "last_nutrition_sent_on": None,
        "last_measurements_sent_on": None,
        "last_photos_sent_on": None,
    }
    defaults.update(overrides)
    return GroupChat(**defaults)


# A Monday (weekday() == 0) that is also the 15th, so nutrition/
# measurements/photos can all be "due" on the same reference date unless
# a test deliberately picks a different one.
MONDAY_15TH = date(2026, 6, 15)


class TestNutritionReminder:
    def test_due_once_at_or_after_scheduled_time(self):
        group = _make_group()
        now = datetime(2026, 6, 15, 20, 0)
        assert ReminderKind.NUTRITION in due_reminders(group, now)

    def test_not_due_before_scheduled_time(self):
        group = _make_group()
        now = datetime(2026, 6, 15, 19, 59)
        assert ReminderKind.NUTRITION not in due_reminders(group, now)

    def test_disabled_type_is_never_due(self):
        group = _make_group(remind_nutrition=False)
        now = datetime(2026, 6, 15, 20, 0)
        assert ReminderKind.NUTRITION not in due_reminders(group, now)

    def test_not_due_again_after_already_sent_today(self):
        group = _make_group(last_nutrition_sent_on=date(2026, 6, 15))
        now = datetime(2026, 6, 15, 21, 0)
        assert ReminderKind.NUTRITION not in due_reminders(group, now)

    def test_due_again_the_next_day_after_being_sent(self):
        group = _make_group(last_nutrition_sent_on=date(2026, 6, 15))
        now = datetime(2026, 6, 16, 20, 0)
        assert ReminderKind.NUTRITION in due_reminders(group, now)

    def test_midnight_boundary_not_due_just_before_midnight_if_before_time(self):
        # 23:59 the day before is well before 20:00 *that* day's schedule
        # in absolute terms, but the check is same-day: 23:59 is after
        # 20:00 on its own calendar day, so it IS due if not yet sent.
        group = _make_group()
        now = datetime(2026, 6, 15, 23, 59)
        assert ReminderKind.NUTRITION in due_reminders(group, now)

    def test_midnight_boundary_resets_for_the_new_day(self):
        # Sent right before midnight on the 15th; at 00:01 on the 16th
        # it's a new calendar day (last_sent_on < today) but before
        # 20:00, so not due yet.
        group = _make_group(last_nutrition_sent_on=date(2026, 6, 15))
        now = datetime(2026, 6, 16, 0, 1)
        assert ReminderKind.NUTRITION not in due_reminders(group, now)

    def test_late_restart_still_sends_once(self):
        """AC: 'бот перезапущений після 20:00' — a restart at, say, 22:00
        with nothing sent yet today still fires (late, but it fires).
        """
        group = _make_group()
        now = datetime(2026, 6, 15, 22, 0)
        assert ReminderKind.NUTRITION in due_reminders(group, now)

    def test_late_restart_does_not_double_send(self):
        # Same late-restart scenario, but it was already sent earlier
        # today (e.g. by the tick right after 20:00, before a later
        # restart) — must not fire again.
        group = _make_group(last_nutrition_sent_on=date(2026, 6, 15))
        now = datetime(2026, 6, 15, 22, 0)
        assert ReminderKind.NUTRITION not in due_reminders(group, now)


class TestMeasurementsReminder:
    def test_due_on_the_configured_weekday(self):
        group = _make_group(measurements_weekday=0)  # Monday
        now = datetime(2026, 6, 15, 9, 0)  # a Monday
        assert ReminderKind.MEASUREMENTS in due_reminders(group, now)

    def test_not_due_on_a_different_weekday(self):
        group = _make_group(measurements_weekday=0)  # Monday
        now = datetime(2026, 6, 16, 9, 0)  # Tuesday
        assert ReminderKind.MEASUREMENTS not in due_reminders(group, now)

    def test_disabled_type_is_never_due(self):
        group = _make_group(remind_measurements=False)
        now = datetime(2026, 6, 15, 9, 0)
        assert ReminderKind.MEASUREMENTS not in due_reminders(group, now)

    def test_not_due_again_next_week_before_time(self):
        group = _make_group(
            measurements_weekday=0, last_measurements_sent_on=date(2026, 6, 15)
        )
        now = datetime(2026, 6, 22, 8, 0)  # next Monday, before 09:00
        assert ReminderKind.MEASUREMENTS not in due_reminders(group, now)

    def test_due_again_next_week_at_time(self):
        group = _make_group(
            measurements_weekday=0, last_measurements_sent_on=date(2026, 6, 15)
        )
        now = datetime(2026, 6, 22, 9, 0)  # next Monday, at 09:00
        assert ReminderKind.MEASUREMENTS in due_reminders(group, now)


class TestPhotosReminder:
    def test_due_on_the_configured_day_of_month(self):
        group = _make_group(photos_day_of_month=15)
        now = datetime(2026, 6, 15, 9, 0)
        assert ReminderKind.PHOTOS in due_reminders(group, now)

    def test_disabled_type_is_never_due(self):
        group = _make_group(remind_photos=False)
        now = datetime(2026, 6, 15, 9, 0)
        assert ReminderKind.PHOTOS not in due_reminders(group, now)

    @pytest.mark.parametrize("day", [29, 30, 31])
    def test_29_to_31_do_not_match_day_of_month_28(self, day):
        """AC: '29-31 число при day_of_month=28' — a lower
        photos_day_of_month must not also fire on a longer month's extra
        tail days; it's an exact match, not 'on or after'.
        """
        group = _make_group(photos_day_of_month=28)
        now = datetime(2026, 1, day, 9, 0)  # January has 31 days
        assert ReminderKind.PHOTOS not in due_reminders(group, now)

    def test_day_of_month_28_is_due_on_the_28th_every_month(self):
        group = _make_group(photos_day_of_month=28)
        now = datetime(2026, 2, 28, 9, 0)  # February, still has a 28th
        assert ReminderKind.PHOTOS in due_reminders(group, now)

    def test_not_due_again_same_month_after_sent(self):
        group = _make_group(
            photos_day_of_month=15, last_photos_sent_on=date(2026, 6, 15)
        )
        now = datetime(2026, 6, 15, 23, 0)
        assert ReminderKind.PHOTOS not in due_reminders(group, now)


class TestMultipleTypesAtOnce:
    def test_all_three_can_be_due_together(self):
        group = _make_group(measurements_weekday=0, photos_day_of_month=15)
        now = datetime(2026, 6, 15, 20, 0)  # Monday the 15th, at 20:00
        result = due_reminders(group, now)
        assert set(result) == {
            ReminderKind.NUTRITION, ReminderKind.MEASUREMENTS, ReminderKind.PHOTOS,
        }

    def test_none_due_returns_empty_list(self):
        group = _make_group(
            remind_nutrition=False, remind_measurements=False, remind_photos=False,
        )
        now = datetime(2026, 6, 15, 20, 0)
        assert due_reminders(group, now) == []


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _register_group(**overrides) -> GroupChat:
    async with async_session_maker() as session:
        group = await GroupChatRepository(session).upsert_active(
            chat_id=overrides.pop("chat_id", -100),
            title="Test Group",
            added_by_telegram_id=1,
        )
        if overrides:
            await GroupChatRepository(session).update_settings(group.chat_id, **overrides)
        await session.commit()
        return group


async def _get_group(chat_id: int = -100) -> GroupChat | None:
    async with async_session_maker() as session:
        return await GroupChatRepository(session).get_by_chat_id(chat_id)


def _fake_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_message = AsyncMock()
    return bot


class TestGroupReminderServiceSendsAndMarksSent:
    async def test_sends_due_reminder_and_marks_it_sent(self):
        await _register_group(nutrition_time="00:00")  # always past scheduled time
        bot = _fake_bot()
        service = GroupReminderService(bot)

        sent = await service.send_due_reminders()

        assert sent >= 1
        bot.send_message.assert_awaited()
        group = await _get_group(-100)
        assert group.last_nutrition_sent_on is not None

    async def test_only_active_groups_are_considered(self):
        await _register_group(chat_id=-200, nutrition_time="00:00")
        async with async_session_maker() as session:
            await GroupChatRepository(session).deactivate(-200)
            await session.commit()

        bot = _fake_bot()
        sent = await GroupReminderService(bot).send_due_reminders()

        assert sent == 0
        bot.send_message.assert_not_awaited()

    async def test_send_failure_leaves_last_sent_on_untouched_for_retry(self):
        await _register_group(nutrition_time="00:00")
        bot = _fake_bot()
        bot.send_message.side_effect = RuntimeError("network blip")

        sent = await GroupReminderService(bot).send_due_reminders()

        assert sent == 0
        group = await _get_group(-100)
        assert group.last_nutrition_sent_on is None  # retried next tick

    async def test_forbidden_error_deactivates_the_group(self):
        await _register_group(nutrition_time="00:00")
        bot = _fake_bot()
        bot.send_message.side_effect = TelegramForbiddenError(
            method=MagicMock(), message="bot was kicked"
        )

        await GroupReminderService(bot).send_due_reminders()

        group = await _get_group(-100)
        assert group.is_active is False

    async def test_not_found_error_deactivates_the_group(self):
        await _register_group(nutrition_time="00:00")
        bot = _fake_bot()
        bot.send_message.side_effect = TelegramNotFound(
            method=MagicMock(), message="chat not found"
        )

        await GroupReminderService(bot).send_due_reminders()

        group = await _get_group(-100)
        assert group.is_active is False

    async def test_nothing_due_sends_nothing(self):
        await _register_group(
            remind_nutrition=False, remind_measurements=False, remind_photos=False,
        )
        bot = _fake_bot()

        sent = await GroupReminderService(bot).send_due_reminders()

        assert sent == 0
        bot.send_message.assert_not_awaited()

    async def test_photos_reminder_has_no_button(self, monkeypatch):
        await _register_group(
            remind_nutrition=False, remind_measurements=False,
            remind_photos=True, photos_time="00:00", photos_day_of_month=15,
        )
        # Pin "now" instead of depending on the real clock's day-of-month
        # matching the fixture's photos_day_of_month.
        monkeypatch.setattr(
            "src.services.group_reminders.to_local_now",
            lambda tz_name: datetime(2026, 6, 15, 12, 0),
        )
        bot = _fake_bot()

        await GroupReminderService(bot).send_due_reminders()

        bot.send_message.assert_awaited_once()
        _, kwargs = bot.send_message.call_args
        assert kwargs.get("reply_markup") is None
