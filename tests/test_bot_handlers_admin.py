"""Tests for admin handlers (src/bot/handlers/admin.py)."""

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.bot.handlers import admin
from src.bot.handlers.admin import AddTrainingStates
from src.database.models import Base
from src.database.repository import (
    BookingRepository,
    TrainingRepository,
    UserRepository,
)
from src.database.session import async_session_maker, engine
from src.utils.datetime_utils import utcnow
from tests.bot_mocks import make_callback, make_fsm_context, make_message, make_telegram_user


@pytest.fixture(autouse=True)
def _mock_google_services():
    """Neither Google Calendar nor Sheets should be hit for real in tests."""
    with patch("src.bot.handlers.admin.GoogleCalendarService") as calendar_cls, patch(
        "src.bot.handlers.admin.GoogleSheetsService"
    ) as sheets_cls:
        calendar_cls.return_value.create_event = _async_return(None)
        calendar_cls.return_value.delete_event = _async_return(True)
        sheets_cls.return_value.add_training_record = _async_return(True)
        yield calendar_cls, sheets_cls


def _async_return(value):
    mock = MagicMock()

    async def _inner(*args, **kwargs):
        return value

    mock.side_effect = _inner
    return mock


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
        defaults = {"title": "Йога", "scheduled_at": utcnow() + timedelta(days=1)}
        defaults.update(overrides)
        training = await TrainingRepository(session).create(**defaults)
        await session.commit()
        return training.id


async def _make_user(**overrides):
    """Create a user, applying any extra field overrides directly (fields
    like ``phone``/``notifications_enabled`` aren't accepted by
    ``get_or_create``, which only handles the identity fields)."""
    telegram_id = overrides.pop("telegram_id", _unique_telegram_id())
    known = {
        k: overrides.pop(k)
        for k in ("first_name", "last_name", "username")
        if k in overrides
    }
    async with async_session_maker() as session:
        user, _ = await UserRepository(session).get_or_create(
            telegram_id=telegram_id, first_name=known.pop("first_name", "Test"), **known
        )
        for field, value in overrides.items():
            setattr(user, field, value)
        await session.commit()
        return telegram_id, user.id


async def _make_booking(user_id, training_id):
    async with async_session_maker() as session:
        booking_row = await BookingRepository(session).create(user_id, training_id)
        await session.commit()
        return booking_row.id


class TestIsAdmin:
    def test_true_for_configured_admin_id(self, monkeypatch):
        monkeypatch.setattr(admin.settings, "admin_user_id", 42)
        assert admin.is_admin(42) is True

    def test_false_for_other_ids(self, monkeypatch):
        monkeypatch.setattr(admin.settings, "admin_user_id", 42)
        assert admin.is_admin(1) is False

    def test_false_when_no_admin_configured(self, monkeypatch):
        monkeypatch.setattr(admin.settings, "admin_user_id", 0)
        assert admin.is_admin(1) is False


class TestAddTrainingHandler:
    async def test_prompts_for_title_and_sets_state(self):
        message = make_message()
        state = make_fsm_context()

        await admin.add_training_handler(message, state)

        message.answer.assert_awaited_once()
        (text,), _ = message.answer.call_args
        assert "Крок 1/5" in text
        assert await state.get_state() == AddTrainingStates.title


class TestProcessTitle:
    async def test_stores_title_and_shows_calendar(self):
        message = make_message(text="Йога для початківців")
        state = make_fsm_context()

        await admin.process_title(message, state)

        assert await state.get_state() == AddTrainingStates.date
        data = await state.get_data()
        assert data["title"] == "Йога для початківців"
        message.answer.assert_awaited_once()
        (text,), kwargs = message.answer.call_args
        assert "Крок 2/5" in text
        assert kwargs["reply_markup"].inline_keyboard  # calendar keyboard present


class TestCalendarCallback:
    async def test_missing_data_does_nothing(self):
        callback = make_callback(data=None)
        state = make_fsm_context()
        await admin.calendar_callback(callback, state)
        callback.answer.assert_not_awaited()

    async def test_non_message_callback_message_does_nothing(self):
        callback = make_callback(data="calendar:cancel", message=MagicMock())
        state = make_fsm_context()
        await admin.calendar_callback(callback, state)
        callback.answer.assert_not_awaited()

    async def test_cancel_clears_state_and_edits_text(self):
        callback = make_callback(data="calendar:cancel")
        state = make_fsm_context()
        await state.set_state(AddTrainingStates.date)

        await admin.calendar_callback(callback, state)

        assert await state.get_state() is None
        callback.message.edit_text.assert_awaited_once_with("❌ Створення тренування скасовано")
        callback.answer.assert_awaited_once()

    async def test_prev_updates_reply_markup_only(self):
        callback = make_callback(data="calendar:prev:2026:6")
        state = make_fsm_context()

        await admin.calendar_callback(callback, state)

        callback.message.edit_reply_markup.assert_awaited_once()
        callback.message.edit_text.assert_not_awaited()
        callback.answer.assert_awaited_once()

    async def test_next_updates_reply_markup_only(self):
        callback = make_callback(data="calendar:next:2026:6")
        state = make_fsm_context()

        await admin.calendar_callback(callback, state)

        callback.message.edit_reply_markup.assert_awaited_once()
        callback.answer.assert_awaited_once()

    async def test_back_shows_calendar_step_text(self):
        callback = make_callback(data="calendar:back:2026:6")
        state = make_fsm_context()

        await admin.calendar_callback(callback, state)

        (text,), _ = callback.message.edit_text.call_args
        assert "Крок 2/5" in text

    async def test_day_selection_moves_to_time_step(self):
        callback = make_callback(data="calendar:day:2026:6:15")
        state = make_fsm_context()

        await admin.calendar_callback(callback, state)

        assert await state.get_state() == AddTrainingStates.time
        data = await state.get_data()
        assert data["selected_date"] == datetime(2026, 6, 15)
        (text,), _ = callback.message.edit_text.call_args
        assert "Крок 3/5" in text
        callback.answer.assert_awaited_once()

    async def test_unrecognized_action_just_answers(self):
        callback = make_callback(data="calendar:whatever")
        state = make_fsm_context()

        await admin.calendar_callback(callback, state)

        callback.message.edit_text.assert_not_awaited()
        callback.message.edit_reply_markup.assert_not_awaited()
        callback.answer.assert_awaited_once()


class TestTimeCallback:
    async def test_missing_data_does_nothing(self):
        callback = make_callback(data=None)
        state = make_fsm_context()
        await admin.time_callback(callback, state)
        callback.answer.assert_not_awaited()

    async def test_cancel_clears_state(self):
        callback = make_callback(data="time:cancel")
        state = make_fsm_context()
        await state.set_state(AddTrainingStates.time)

        await admin.time_callback(callback, state)

        assert await state.get_state() is None
        callback.message.edit_text.assert_awaited_once_with("❌ Створення тренування скасовано")

    async def test_select_moves_to_duration_step(self):
        callback = make_callback(data="time:select:2026:6:15:9:30")
        state = make_fsm_context()

        await admin.time_callback(callback, state)

        assert await state.get_state() == AddTrainingStates.duration
        data = await state.get_data()
        assert data["scheduled_at"] == datetime(2026, 6, 15, 9, 30)
        (text,), _ = callback.message.edit_text.call_args
        assert "Крок 4/5" in text

    async def test_unrecognized_action_just_answers(self):
        callback = make_callback(data="time:whatever")
        state = make_fsm_context()

        await admin.time_callback(callback, state)

        callback.message.edit_text.assert_not_awaited()
        callback.answer.assert_awaited_once()


class TestDurationCallback:
    async def test_missing_data_does_nothing(self):
        callback = make_callback(data=None)
        state = make_fsm_context()
        await admin.duration_callback(callback, state)
        callback.answer.assert_not_awaited()

    async def test_cancel_clears_state(self):
        callback = make_callback(data="duration:cancel")
        state = make_fsm_context()
        await state.set_state(AddTrainingStates.duration)

        await admin.duration_callback(callback, state)

        assert await state.get_state() is None
        callback.message.edit_text.assert_awaited_once_with("❌ Створення тренування скасовано")

    async def test_selection_moves_to_participants_step(self):
        callback = make_callback(data="duration:60")
        state = make_fsm_context()

        await admin.duration_callback(callback, state)

        assert await state.get_state() == AddTrainingStates.max_participants
        data = await state.get_data()
        assert data["duration"] == 60
        (text,), kwargs = callback.message.edit_text.call_args
        assert "Крок 5/5" in text
        assert kwargs["reply_markup"].inline_keyboard


class TestParticipantsCallback:
    async def test_missing_data_does_nothing(self):
        callback = make_callback(data=None)
        state = make_fsm_context()
        await admin.participants_callback(callback, state)
        callback.answer.assert_not_awaited()

    async def test_cancel_clears_state(self):
        callback = make_callback(data="participants:cancel")
        state = make_fsm_context()
        await state.set_state(AddTrainingStates.max_participants)

        await admin.participants_callback(callback, state)

        assert await state.get_state() is None
        callback.message.edit_text.assert_awaited_once_with("❌ Створення тренування скасовано")

    async def test_creates_training_and_shows_summary(self, _mock_google_services):
        calendar_cls, sheets_cls = _mock_google_services
        callback = make_callback(data="participants:10")
        state = make_fsm_context()
        await state.update_data(
            title="Кросфіт",
            scheduled_at=utcnow() + timedelta(days=5),
            duration=60,
        )

        await admin.participants_callback(callback, state)

        callback.message.edit_text.assert_awaited_once()
        (text,), _ = callback.message.edit_text.call_args
        assert "Кросфіт" in text
        assert "10" in text
        callback.message.answer.assert_awaited_once()
        callback.answer.assert_awaited_once_with("✅ Тренування створено!")
        assert await state.get_state() is None
        sheets_cls.return_value.add_training_record.assert_called_once()

        async with async_session_maker() as session:
            trainings = await TrainingRepository(session).get_upcoming(limit=10)
            assert len(trainings) == 1
            assert trainings[0].title == "Кросфіт"

    async def test_stores_google_calendar_event_id_when_sync_succeeds(
        self, _mock_google_services
    ):
        calendar_cls, _ = _mock_google_services
        calendar_cls.return_value.create_event = _async_return("gcal-event-123")
        callback = make_callback(data="participants:5")
        state = make_fsm_context()
        await state.update_data(
            title="Йога", scheduled_at=utcnow() + timedelta(days=5), duration=60
        )

        await admin.participants_callback(callback, state)

        async with async_session_maker() as session:
            trainings = await TrainingRepository(session).get_upcoming(limit=10)
            assert trainings[0].google_calendar_event_id == "gcal-event-123"

    async def test_training_still_created_if_calendar_sync_fails(
        self, _mock_google_services
    ):
        calendar_cls, _ = _mock_google_services

        def _raise(*args, **kwargs):
            raise RuntimeError("boom")

        calendar_cls.return_value.create_event.side_effect = _raise
        callback = make_callback(data="participants:5")
        state = make_fsm_context()
        await state.update_data(
            title="Йога", scheduled_at=utcnow() + timedelta(days=5), duration=60
        )

        await admin.participants_callback(callback, state)

        callback.answer.assert_awaited_once_with("✅ Тренування створено!")

    async def test_training_still_created_if_sheets_sync_fails(
        self, _mock_google_services
    ):
        _, sheets_cls = _mock_google_services

        def _raise(*args, **kwargs):
            raise RuntimeError("boom")

        sheets_cls.return_value.add_training_record.side_effect = _raise
        callback = make_callback(data="participants:5")
        state = make_fsm_context()
        await state.update_data(
            title="Йога", scheduled_at=utcnow() + timedelta(days=5), duration=60
        )

        await admin.participants_callback(callback, state)

        callback.answer.assert_awaited_once_with("✅ Тренування створено!")


class TestIgnoreCallback:
    async def test_just_answers(self):
        callback = make_callback(data="ignore")
        await admin.ignore_callback(callback)
        callback.answer.assert_awaited_once()


class TestStatisticsHandler:
    async def test_reports_counts(self):
        await _make_user(notifications_enabled=True)
        await _make_user(notifications_enabled=True)
        training_id = await _make_training()
        _, user_id = await _make_user()
        await _make_booking(user_id, training_id)

        message = make_message()
        await admin.statistics_handler(message)

        message.answer.assert_awaited_once()
        (text,), _ = message.answer.call_args
        assert "Зареєстрованих користувачів: 3" in text
        assert "Запланованих тренувань: 1" in text
        assert "Активних записів: 1" in text


class TestAdminParticipantsCallback:
    async def test_missing_data_does_nothing(self):
        callback = make_callback(data=None)
        await admin.admin_participants_callback(callback)
        callback.answer.assert_not_awaited()

    async def test_non_admin_gets_no_access(self, monkeypatch):
        monkeypatch.setattr(admin.settings, "admin_user_id", 0)
        training_id = await _make_training()
        callback = make_callback(data=f"admin_participants:{training_id}")

        await admin.admin_participants_callback(callback)

        callback.answer.assert_awaited_once_with("❌ Немає доступу", show_alert=True)

    async def test_unknown_training_shows_alert(self, monkeypatch):
        admin_id = _unique_telegram_id()
        monkeypatch.setattr(admin.settings, "admin_user_id", admin_id)
        callback = make_callback(
            data="admin_participants:999999",
            from_user=make_telegram_user(user_id=admin_id),
        )

        await admin.admin_participants_callback(callback)

        callback.answer.assert_awaited_once_with("❌ Тренування не знайдено", show_alert=True)

    async def test_lists_participants_with_contact_info(self, monkeypatch):
        admin_id = _unique_telegram_id()
        monkeypatch.setattr(admin.settings, "admin_user_id", admin_id)
        training_id = await _make_training(title="Йога")
        _, user_id = await _make_user(username="andrii", phone="+380501234567")
        await _make_booking(user_id, training_id)

        callback = make_callback(
            data=f"admin_participants:{training_id}",
            from_user=make_telegram_user(user_id=admin_id),
        )

        await admin.admin_participants_callback(callback)

        (text,), _ = callback.message.edit_text.call_args
        assert "@andrii" in text
        assert "+380501234567" in text
        callback.answer.assert_awaited_once()

    async def test_no_participants_shows_placeholder(self, monkeypatch):
        admin_id = _unique_telegram_id()
        monkeypatch.setattr(admin.settings, "admin_user_id", admin_id)
        training_id = await _make_training()
        callback = make_callback(
            data=f"admin_participants:{training_id}",
            from_user=make_telegram_user(user_id=admin_id),
        )

        await admin.admin_participants_callback(callback)

        (text,), _ = callback.message.edit_text.call_args
        assert "Поки немає записів" in text


class TestAdminCancelTrainingCallback:
    async def test_missing_data_does_nothing(self):
        callback = make_callback(data=None)
        await admin.admin_cancel_training_callback(callback)
        callback.answer.assert_not_awaited()

    async def test_non_admin_gets_no_access(self, monkeypatch):
        monkeypatch.setattr(admin.settings, "admin_user_id", 0)
        training_id = await _make_training()
        callback = make_callback(data=f"admin_cancel:{training_id}")

        await admin.admin_cancel_training_callback(callback)

        callback.answer.assert_awaited_once_with("❌ Немає доступу", show_alert=True)

    async def test_unknown_training_shows_alert(self, monkeypatch):
        admin_id = _unique_telegram_id()
        monkeypatch.setattr(admin.settings, "admin_user_id", admin_id)
        callback = make_callback(
            data="admin_cancel:999999", from_user=make_telegram_user(user_id=admin_id)
        )

        await admin.admin_cancel_training_callback(callback)

        callback.answer.assert_awaited_once_with("❌ Тренування не знайдено", show_alert=True)

    async def test_cancels_training_and_shows_schedule(self, monkeypatch):
        admin_id = _unique_telegram_id()
        monkeypatch.setattr(admin.settings, "admin_user_id", admin_id)
        training_id = await _make_training(title="Йога")
        callback = make_callback(
            data=f"admin_cancel:{training_id}", from_user=make_telegram_user(user_id=admin_id)
        )

        await admin.admin_cancel_training_callback(callback)

        callback.answer.assert_awaited_once_with("✅ Тренування скасовано", show_alert=True)
        callback.message.edit_text.assert_awaited_once()

        async with async_session_maker() as session:
            training = await TrainingRepository(session).get_by_id(training_id)
            assert training.is_cancelled is True

    async def test_also_deletes_calendar_event_when_present(
        self, monkeypatch, _mock_google_services
    ):
        calendar_cls, _ = _mock_google_services
        admin_id = _unique_telegram_id()
        monkeypatch.setattr(admin.settings, "admin_user_id", admin_id)
        training_id = await _make_training()
        async with async_session_maker() as session:
            await TrainingRepository(session).update_google_event_id(
                training_id, "gcal-event-1"
            )
            await session.commit()

        callback = make_callback(
            data=f"admin_cancel:{training_id}", from_user=make_telegram_user(user_id=admin_id)
        )
        await admin.admin_cancel_training_callback(callback)

        calendar_cls.return_value.delete_event.assert_called_once_with("gcal-event-1")

    async def test_cancellation_succeeds_even_if_calendar_sync_fails(
        self, monkeypatch, _mock_google_services
    ):
        calendar_cls, _ = _mock_google_services

        def _raise(*args, **kwargs):
            raise RuntimeError("boom")

        calendar_cls.return_value.delete_event.side_effect = _raise
        admin_id = _unique_telegram_id()
        monkeypatch.setattr(admin.settings, "admin_user_id", admin_id)
        training_id = await _make_training()
        async with async_session_maker() as session:
            await TrainingRepository(session).update_google_event_id(
                training_id, "gcal-event-1"
            )
            await session.commit()

        callback = make_callback(
            data=f"admin_cancel:{training_id}", from_user=make_telegram_user(user_id=admin_id)
        )
        await admin.admin_cancel_training_callback(callback)

        callback.answer.assert_awaited_once_with("✅ Тренування скасовано", show_alert=True)


class TestAdminBackCallback:
    async def test_non_message_callback_message_does_nothing(self):
        callback = make_callback(message=MagicMock())
        await admin.admin_back_callback(callback)
        callback.answer.assert_not_awaited()

    async def test_shows_schedule(self):
        await _make_training(title="Пілатес")
        callback = make_callback()

        await admin.admin_back_callback(callback)

        callback.message.edit_text.assert_awaited_once()
        (text,), kwargs = callback.message.edit_text.call_args
        assert "Розклад тренувань" in text
        buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
        assert any("Пілатес" in b.text for b in buttons)
        callback.answer.assert_awaited_once()


class TestAdminCommand:
    async def test_no_from_user_does_nothing(self):
        message = make_message(from_user=None)
        await admin.admin_command(message)
        message.answer.assert_not_awaited()

    async def test_non_admin_gets_no_access_message(self, monkeypatch):
        monkeypatch.setattr(admin.settings, "admin_user_id", 0)
        message = make_message(from_user=make_telegram_user(user_id=_unique_telegram_id()))

        await admin.admin_command(message)

        message.answer.assert_awaited_once_with("❌ У вас немає прав адміністратора")

    async def test_admin_gets_menu(self, monkeypatch):
        admin_id = _unique_telegram_id()
        monkeypatch.setattr(admin.settings, "admin_user_id", admin_id)
        message = make_message(from_user=make_telegram_user(user_id=admin_id))

        await admin.admin_command(message)

        message.answer.assert_awaited_once()
        (text,), kwargs = message.answer.call_args
        assert "Адмін-панель" in text
        assert kwargs["parse_mode"] == "Markdown"
