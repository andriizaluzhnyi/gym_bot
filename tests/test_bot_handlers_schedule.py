"""Tests for schedule handlers (src/bot/handlers/schedule.py)."""

import uuid
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from src.bot.handlers import schedule
from src.database.models import Base
from src.database.repository import BookingRepository, TrainingRepository, UserRepository
from src.database.session import async_session_maker, engine
from src.utils.datetime_utils import utcnow
from tests.bot_mocks import make_callback, make_message, make_telegram_user


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


def _unique_telegram_id() -> int:
    return uuid.uuid4().int % (2**31)


async def _make_training(**overrides):
    async with async_session_maker() as session:
        defaults = {
            "title": "Йога",
            "scheduled_at": utcnow() + timedelta(days=1),
        }
        defaults.update(overrides)
        training = await TrainingRepository(session).create(**defaults)
        await session.commit()
        return training.id


class TestScheduleHandler:
    async def test_no_upcoming_trainings_shows_placeholder(self):
        message = make_message(text="/schedule")
        await schedule.schedule_handler(message)

        message.answer.assert_awaited_once()
        (text,), _ = message.answer.call_args
        assert "немає запланованих тренувань" in text

    async def test_lists_upcoming_trainings(self):
        await _make_training(title="Йога")
        message = make_message(text="/schedule")

        await schedule.schedule_handler(message)

        message.answer.assert_awaited_once()
        (text,), kwargs = message.answer.call_args
        assert "Розклад тренувань" in text
        keyboard = kwargs["reply_markup"]
        buttons = [b for row in keyboard.inline_keyboard for b in row]
        assert any("Йога" in b.text for b in buttons)


class TestBackToScheduleCallback:
    async def test_ignores_non_message_callback_message(self):
        callback = make_callback(data="back_to_schedule", message=MagicMock())
        await schedule.back_to_schedule_callback(callback)
        callback.answer.assert_not_awaited()

    async def test_edits_message_with_schedule(self):
        await _make_training(title="Бокс")
        callback = make_callback(data="back_to_schedule")

        await schedule.back_to_schedule_callback(callback)

        callback.message.edit_text.assert_awaited_once()
        callback.answer.assert_awaited_once()


class TestTrainingDetailCallback:
    async def test_missing_data_does_nothing(self):
        callback = make_callback(data=None)
        await schedule.training_detail_callback(callback)
        callback.answer.assert_not_awaited()

    async def test_unknown_training_shows_alert(self):
        callback = make_callback(data="training:999999")
        await schedule.training_detail_callback(callback)
        callback.answer.assert_awaited_once_with(
            "❌ Тренування не знайдено", show_alert=True
        )

    async def test_shows_details_for_user_without_booking(self):
        training_id = await _make_training(
            title="Кросфіт", location="Зал 1", description="Інтенсивне тренування"
        )
        telegram_id = _unique_telegram_id()
        callback = make_callback(
            data=f"training:{training_id}", from_user=make_telegram_user(user_id=telegram_id)
        )

        await schedule.training_detail_callback(callback)

        callback.message.edit_text.assert_awaited_once()
        (text,), kwargs = callback.message.edit_text.call_args
        assert "Кросфіт" in text
        assert "Зал 1" in text
        assert "Інтенсивне тренування" in text
        assert "Ви записані" not in text
        buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
        assert any(b.callback_data == f"book:{training_id}" for b in buttons)
        callback.answer.assert_awaited_once()

    async def test_shows_booked_status_for_user_with_booking(self):
        training_id = await _make_training(title="Йога")
        telegram_id = _unique_telegram_id()

        async with async_session_maker() as session:
            user, _ = await UserRepository(session).get_or_create(
                telegram_id=telegram_id, first_name="Andrii"
            )
            await BookingRepository(session).create(user.id, training_id)
            await session.commit()

        callback = make_callback(
            data=f"training:{training_id}", from_user=make_telegram_user(user_id=telegram_id)
        )

        await schedule.training_detail_callback(callback)

        (text,), kwargs = callback.message.edit_text.call_args
        assert "Ви записані" in text
        buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
        assert any(b.callback_data == f"cancel_booking:{training_id}" for b in buttons)

    async def test_full_training_offers_notify_instead_of_book(self):
        training_id = await _make_training(title="Йога", max_participants=1)
        filler_telegram_id = _unique_telegram_id()
        async with async_session_maker() as session:
            filler, _ = await UserRepository(session).get_or_create(
                telegram_id=filler_telegram_id, first_name="Filler"
            )
            await BookingRepository(session).create(filler.id, training_id)
            await session.commit()

        callback = make_callback(
            data=f"training:{training_id}",
            from_user=make_telegram_user(user_id=_unique_telegram_id()),
        )

        await schedule.training_detail_callback(callback)

        (_, kwargs) = callback.message.edit_text.call_args
        buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
        assert any(b.callback_data == f"notify_spot:{training_id}" for b in buttons)


class TestNoTrainingsCallback:
    async def test_answers_with_alert(self):
        callback = make_callback(data="no_trainings")
        await schedule.no_trainings_callback(callback)
        callback.answer.assert_awaited_once_with(
            "Немає доступних тренувань", show_alert=True
        )
