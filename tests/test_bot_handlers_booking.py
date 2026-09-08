"""Tests for booking handlers (src/bot/handlers/booking.py)."""

import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.bot.handlers import booking
from src.database.models import Base
from src.database.repository import BookingRepository, TrainingRepository, UserRepository
from src.database.session import async_session_maker, engine
from src.utils.datetime_utils import utcnow
from tests.bot_mocks import make_callback, make_message, make_telegram_user


@pytest.fixture(autouse=True)
def _mock_google_sheets():
    """None of these handlers should depend on live Google Sheets access;
    every test patches it so a missing/misconfigured integration never
    turns into a spurious failure or a real network call."""
    with patch("src.bot.handlers.booking.GoogleSheetsService") as mock_cls:
        instance = mock_cls.return_value
        instance.add_booking_record = MagicMock()
        instance.update_booking_status = MagicMock()

        async def _ok(*args, **kwargs):
            return True

        instance.add_booking_record.side_effect = _ok
        instance.update_booking_status.side_effect = _ok
        yield mock_cls


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


def _unique_telegram_id() -> int:
    return uuid.uuid4().int % (2**31)


async def _make_user(telegram_id: int | None = None, **overrides):
    telegram_id = telegram_id or _unique_telegram_id()
    async with async_session_maker() as session:
        user, _ = await UserRepository(session).get_or_create(
            telegram_id=telegram_id, first_name="Test", **overrides
        )
        await session.commit()
        return telegram_id, user.id


async def _make_training(**overrides):
    async with async_session_maker() as session:
        defaults = {"title": "Йога", "scheduled_at": utcnow() + timedelta(days=1)}
        defaults.update(overrides)
        training = await TrainingRepository(session).create(**defaults)
        await session.commit()
        return training.id


async def _make_booking(user_id, training_id):
    async with async_session_maker() as session:
        booking_row = await BookingRepository(session).create(user_id, training_id)
        await session.commit()
        return booking_row.id


class TestMyBookingsHandler:
    async def test_no_from_user_does_nothing(self):
        message = make_message(from_user=None)
        await booking.my_bookings_handler(message)
        message.answer.assert_not_awaited()

    async def test_unknown_user_prompts_start(self):
        message = make_message(from_user=make_telegram_user(user_id=_unique_telegram_id()))
        await booking.my_bookings_handler(message)
        message.answer.assert_awaited_once_with("❌ Спочатку натисніть /start")

    async def test_no_bookings_shows_placeholder(self):
        telegram_id, _ = await _make_user()
        message = make_message(from_user=make_telegram_user(user_id=telegram_id))

        await booking.my_bookings_handler(message)

        (text,), _ = message.answer.call_args
        assert "немає активних записів" in text

    async def test_lists_upcoming_bookings(self):
        telegram_id, user_id = await _make_user()
        training_id = await _make_training(title="Бокс")
        await _make_booking(user_id, training_id)
        message = make_message(from_user=make_telegram_user(user_id=telegram_id))

        await booking.my_bookings_handler(message)

        (text,), kwargs = message.answer.call_args
        assert "Ваші активні записи" in text
        buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
        assert any("Бокс" in b.text for b in buttons)


class TestBookTrainingCallback:
    async def test_missing_data_does_nothing(self):
        callback = make_callback(data=None)
        await booking.book_training_callback(callback)
        callback.answer.assert_not_awaited()

    async def test_non_message_callback_message_does_nothing(self):
        callback = make_callback(data="book:1", message=MagicMock())
        await booking.book_training_callback(callback)
        callback.answer.assert_not_awaited()

    async def test_unknown_user_prompts_start(self):
        training_id = await _make_training()
        callback = make_callback(
            data=f"book:{training_id}",
            from_user=make_telegram_user(user_id=_unique_telegram_id()),
        )
        await booking.book_training_callback(callback)
        callback.answer.assert_awaited_once_with(
            "❌ Спочатку натисніть /start", show_alert=True
        )

    async def test_unknown_training_shows_alert(self):
        telegram_id, _ = await _make_user()
        callback = make_callback(
            data="book:999999", from_user=make_telegram_user(user_id=telegram_id)
        )
        await booking.book_training_callback(callback)
        callback.answer.assert_awaited_once_with(
            "❌ Тренування не знайдено", show_alert=True
        )

    async def test_already_booked_shows_alert(self):
        telegram_id, user_id = await _make_user()
        training_id = await _make_training()
        await _make_booking(user_id, training_id)
        callback = make_callback(
            data=f"book:{training_id}", from_user=make_telegram_user(user_id=telegram_id)
        )

        await booking.book_training_callback(callback)

        callback.answer.assert_awaited_once_with(
            "❌ Ви вже записані на це тренування", show_alert=True
        )

    async def test_full_training_shows_alert(self):
        telegram_id, _ = await _make_user()
        training_id = await _make_training(max_participants=1)
        _, filler_id = await _make_user()
        await _make_booking(filler_id, training_id)

        callback = make_callback(
            data=f"book:{training_id}", from_user=make_telegram_user(user_id=telegram_id)
        )
        await booking.book_training_callback(callback)

        callback.answer.assert_awaited_once_with(
            "❌ На жаль, вільних місць немає", show_alert=True
        )

    async def test_successful_booking(self, _mock_google_sheets):
        telegram_id, user_id = await _make_user()
        training_id = await _make_training(title="Кросфіт")
        callback = make_callback(
            data=f"book:{training_id}", from_user=make_telegram_user(user_id=telegram_id)
        )

        await booking.book_training_callback(callback)

        callback.message.edit_text.assert_awaited_once()
        (text,), _ = callback.message.edit_text.call_args
        assert "Кросфіт" in text
        callback.answer.assert_awaited_once_with("✅ Успішно записано!")
        _mock_google_sheets.return_value.add_booking_record.assert_called_once()

        async with async_session_maker() as session:
            existing = await BookingRepository(session).get_user_booking_for_training(
                user_id, training_id
            )
            assert existing is not None

    async def test_booking_succeeds_even_if_sheets_sync_fails(self, _mock_google_sheets):
        _mock_google_sheets.return_value.add_booking_record.side_effect = RuntimeError("boom")
        telegram_id, user_id = await _make_user()
        training_id = await _make_training()
        callback = make_callback(
            data=f"book:{training_id}", from_user=make_telegram_user(user_id=telegram_id)
        )

        await booking.book_training_callback(callback)

        callback.answer.assert_awaited_once_with("✅ Успішно записано!")


class TestCancelBookingFromTrainingCallback:
    async def test_missing_data_does_nothing(self):
        callback = make_callback(data=None)
        await booking.cancel_booking_from_training_callback(callback)
        callback.answer.assert_not_awaited()

    async def test_shows_confirmation(self):
        callback = make_callback(data="cancel_booking:5")
        await booking.cancel_booking_from_training_callback(callback)

        callback.message.edit_text.assert_awaited_once()
        (text,), kwargs = callback.message.edit_text.call_args
        assert "Підтвердження скасування" in text
        buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
        assert any(b.callback_data == "confirm_cancel:5" for b in buttons)
        callback.answer.assert_awaited_once()


class TestConfirmCancelCallback:
    async def test_missing_data_does_nothing(self):
        callback = make_callback(data=None)
        await booking.confirm_cancel_callback(callback)
        callback.answer.assert_not_awaited()

    async def test_unknown_user_shows_error(self):
        training_id = await _make_training()
        callback = make_callback(
            data=f"confirm_cancel:{training_id}",
            from_user=make_telegram_user(user_id=_unique_telegram_id()),
        )
        await booking.confirm_cancel_callback(callback)
        callback.answer.assert_awaited_once_with("❌ Помилка", show_alert=True)

    async def test_no_booking_shows_alert(self):
        telegram_id, _ = await _make_user()
        training_id = await _make_training()
        callback = make_callback(
            data=f"confirm_cancel:{training_id}",
            from_user=make_telegram_user(user_id=telegram_id),
        )
        await booking.confirm_cancel_callback(callback)
        callback.answer.assert_awaited_once_with("❌ Запис не знайдено", show_alert=True)

    async def test_cancels_booking_and_shows_schedule(self, _mock_google_sheets):
        telegram_id, user_id = await _make_user()
        training_id = await _make_training(title="Йога")
        booking_id = await _make_booking(user_id, training_id)
        callback = make_callback(
            data=f"confirm_cancel:{training_id}",
            from_user=make_telegram_user(user_id=telegram_id),
        )

        await booking.confirm_cancel_callback(callback)

        callback.message.edit_text.assert_awaited_once()
        (text,), _ = callback.message.edit_text.call_args
        assert "Запис скасовано" in text
        assert "Йога" in text
        callback.answer.assert_awaited_once_with("Запис скасовано")
        _mock_google_sheets.return_value.update_booking_status.assert_called_once_with(
            booking_id, "cancelled"
        )

        async with async_session_maker() as session:
            cancelled = await BookingRepository(session).get_by_id(booking_id)
            assert cancelled.status == "cancelled"

    async def test_cancellation_succeeds_even_if_sheets_sync_fails(
        self, _mock_google_sheets
    ):
        _mock_google_sheets.return_value.update_booking_status.side_effect = RuntimeError(
            "boom"
        )
        telegram_id, user_id = await _make_user()
        training_id = await _make_training()
        await _make_booking(user_id, training_id)
        callback = make_callback(
            data=f"confirm_cancel:{training_id}",
            from_user=make_telegram_user(user_id=telegram_id),
        )

        await booking.confirm_cancel_callback(callback)

        callback.answer.assert_awaited_once_with("Запис скасовано")


class TestCancelBookingByIdCallback:
    async def test_missing_data_does_nothing(self):
        callback = make_callback(data=None)
        await booking.cancel_booking_by_id_callback(callback)
        callback.answer.assert_not_awaited()

    async def test_unknown_booking_shows_alert(self):
        callback = make_callback(data="cancel_booking_id:999999")
        await booking.cancel_booking_by_id_callback(callback)
        callback.answer.assert_awaited_once_with("❌ Запис не знайдено", show_alert=True)

    async def test_cancels_booking(self):
        _, user_id = await _make_user()
        training_id = await _make_training(title="Плавання")
        booking_id = await _make_booking(user_id, training_id)
        callback = make_callback(data=f"cancel_booking_id:{booking_id}")

        await booking.cancel_booking_by_id_callback(callback)

        (text,), _ = callback.message.edit_text.call_args
        assert "Плавання" in text
        callback.answer.assert_awaited_once_with("Запис скасовано")

        async with async_session_maker() as session:
            cancelled = await BookingRepository(session).get_by_id(booking_id)
            assert cancelled.status == "cancelled"


class TestMyBookingDetailCallback:
    async def test_missing_data_does_nothing(self):
        callback = make_callback(data=None)
        await booking.my_booking_detail_callback(callback)
        callback.answer.assert_not_awaited()

    async def test_unknown_booking_shows_alert(self):
        callback = make_callback(data="my_booking:999999")
        await booking.my_booking_detail_callback(callback)
        callback.answer.assert_awaited_once_with("❌ Запис не знайдено", show_alert=True)

    async def test_shows_booking_detail(self):
        _, user_id = await _make_user()
        training_id = await _make_training(title="Пілатес", location="Зал 2")
        booking_id = await _make_booking(user_id, training_id)
        callback = make_callback(data=f"my_booking:{booking_id}")

        await booking.my_booking_detail_callback(callback)

        (text,), kwargs = callback.message.edit_text.call_args
        assert "Пілатес" in text
        assert "Зал 2" in text
        assert "Ви записані" in text
        buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
        assert any(b.callback_data == f"cancel_booking:{training_id}" for b in buttons)
        callback.answer.assert_awaited_once()


class TestNoBookingsCallback:
    async def test_answers_with_alert(self):
        callback = make_callback(data="no_bookings")
        await booking.no_bookings_callback(callback)
        callback.answer.assert_awaited_once_with(
            "У вас немає активних записів", show_alert=True
        )
