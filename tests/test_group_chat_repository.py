"""Tests for GYM-32: GroupChatRepository (src/database/repository.py) —
the CRUD/settings layer GYM-33's `/reminders` command and GYM-34's
scheduled jobs will build on; the bot handler's own join/leave wiring is
covered in tests/test_bot_handlers_group_reminders.py.
"""

from datetime import date

import pytest

from src.database.models import Base
from src.database.repository import GroupChatRepository
from src.database.session import async_session_maker, engine


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


class TestUpsertActive:
    async def test_creates_a_new_row_with_defaults(self):
        async with async_session_maker() as session:
            group = await GroupChatRepository(session).upsert_active(
                chat_id=-100, title="My Gym Group", added_by_telegram_id=1
            )
            await session.commit()

            assert group.chat_id == -100
            assert group.title == "My Gym Group"
            assert group.is_active is True
            assert group.added_by_telegram_id == 1
            assert group.remind_nutrition is True
            assert group.nutrition_time == "20:00"
            assert group.remind_measurements is True
            assert group.measurements_weekday == 0
            assert group.measurements_time == "09:00"
            assert group.remind_photos is False
            assert group.photos_day_of_month == 1
            assert group.photos_time == "09:00"
            assert group.last_nutrition_sent_on is None
            assert group.last_measurements_sent_on is None
            assert group.last_photos_sent_on is None

    async def test_reactivating_an_existing_row_preserves_settings(self):
        async with async_session_maker() as session:
            repo = GroupChatRepository(session)
            await repo.upsert_active(chat_id=-100, title="Old", added_by_telegram_id=1)
            await repo.update_settings(-100, nutrition_time="18:00", remind_photos=True)
            await repo.deactivate(-100)
            await session.commit()

        async with async_session_maker() as session:
            repo = GroupChatRepository(session)
            group = await repo.upsert_active(
                chat_id=-100, title="New Title", added_by_telegram_id=999,
            )
            await session.commit()

            assert group.is_active is True
            assert group.title == "New Title"
            # Settings survive the leave/rejoin cycle.
            assert group.nutrition_time == "18:00"
            assert group.remind_photos is True
            # added_by is only set on the original insert, not on rejoin.
            assert group.added_by_telegram_id == 1


class TestDeactivate:
    async def test_flips_is_active_off(self):
        async with async_session_maker() as session:
            repo = GroupChatRepository(session)
            await repo.upsert_active(chat_id=-100, title=None, added_by_telegram_id=1)
            await session.commit()

            result = await repo.deactivate(-100)
            await session.commit()

            assert result is True
            group = await repo.get_by_chat_id(-100)
            assert group.is_active is False

    async def test_returns_false_for_unknown_chat(self):
        async with async_session_maker() as session:
            result = await GroupChatRepository(session).deactivate(-999)
            assert result is False


class TestGetActive:
    async def test_only_returns_active_groups(self):
        async with async_session_maker() as session:
            repo = GroupChatRepository(session)
            await repo.upsert_active(chat_id=-1, title="A", added_by_telegram_id=1)
            await repo.upsert_active(chat_id=-2, title="B", added_by_telegram_id=1)
            await repo.deactivate(-2)
            await session.commit()

            active = await repo.get_active()
            assert {g.chat_id for g in active} == {-1}

    async def test_empty_when_no_groups(self):
        async with async_session_maker() as session:
            assert await GroupChatRepository(session).get_active() == []


class TestUpdateSettings:
    async def test_updates_only_provided_fields(self):
        async with async_session_maker() as session:
            repo = GroupChatRepository(session)
            await repo.upsert_active(chat_id=-100, title=None, added_by_telegram_id=1)
            await session.commit()

            group = await repo.update_settings(
                -100, remind_nutrition=False, measurements_time="10:00",
            )
            await session.commit()

            assert group.remind_nutrition is False
            assert group.measurements_time == "10:00"
            # Untouched fields keep their defaults.
            assert group.nutrition_time == "20:00"
            assert group.remind_measurements is True
            assert group.remind_photos is False

    async def test_returns_none_for_unknown_chat(self):
        async with async_session_maker() as session:
            result = await GroupChatRepository(session).update_settings(
                -999, remind_nutrition=False
            )
            assert result is None

    async def test_all_settable_fields(self):
        async with async_session_maker() as session:
            repo = GroupChatRepository(session)
            await repo.upsert_active(chat_id=-100, title=None, added_by_telegram_id=1)
            await session.commit()

            group = await repo.update_settings(
                -100,
                remind_nutrition=False,
                nutrition_time="21:00",
                remind_measurements=False,
                measurements_weekday=3,
                measurements_time="08:00",
                remind_photos=True,
                photos_day_of_month=15,
                photos_time="07:30",
            )
            await session.commit()

            assert group.remind_nutrition is False
            assert group.nutrition_time == "21:00"
            assert group.remind_measurements is False
            assert group.measurements_weekday == 3
            assert group.measurements_time == "08:00"
            assert group.remind_photos is True
            assert group.photos_day_of_month == 15
            assert group.photos_time == "07:30"


class TestMarkSent:
    async def test_sets_the_matching_last_sent_column(self):
        async with async_session_maker() as session:
            repo = GroupChatRepository(session)
            await repo.upsert_active(chat_id=-100, title=None, added_by_telegram_id=1)
            await session.commit()

            await repo.mark_sent(-100, "nutrition", date(2026, 1, 15))
            await repo.mark_sent(-100, "measurements", date(2026, 1, 12))
            await repo.mark_sent(-100, "photos", date(2026, 1, 1))
            await session.commit()

            group = await repo.get_by_chat_id(-100)
            assert group.last_nutrition_sent_on == date(2026, 1, 15)
            assert group.last_measurements_sent_on == date(2026, 1, 12)
            assert group.last_photos_sent_on == date(2026, 1, 1)

    async def test_unknown_reminder_type_raises(self):
        async with async_session_maker() as session:
            repo = GroupChatRepository(session)
            await repo.upsert_active(chat_id=-100, title=None, added_by_telegram_id=1)
            await session.commit()

            with pytest.raises(ValueError):
                await repo.mark_sent(-100, "workouts", date(2026, 1, 1))

    async def test_no_op_for_unknown_chat(self):
        async with async_session_maker() as session:
            # Should not raise.
            await GroupChatRepository(session).mark_sent(
                -999, "nutrition", date(2026, 1, 1)
            )
