"""Admin handlers for managing trainings."""

from contextlib import suppress
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from src.bot.calendar_picker import (
    create_calendar,
    create_duration_picker,
    create_participants_picker,
    create_time_picker,
    get_next_month,
    get_prev_month,
    process_calendar_callback,
)
from src.bot.keyboards import (
    get_admin_menu_keyboard,
    get_admin_training_keyboard,
    get_schedule_inline_keyboard,
)
from src.config import get_settings
from src.database.repository import BookingRepository, TrainingRepository, UserRepository
from src.database.session import async_session_maker
from src.services.google_calendar import GoogleCalendarService
from src.services.google_sheets import GoogleSheetsService

router = Router()
settings = get_settings()


class AddTrainingStates(StatesGroup):
    """States for adding a training."""

    title = State()
    date = State()
    time = State()
    duration = State()
    max_participants = State()
    location = State()
    description = State()


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return user_id in settings.admin_user_ids


@router.message(F.text == "➕ Додати тренування")
async def add_training_handler(message: Message, state: FSMContext) -> None:
    """Start adding a new training."""
    # if not is_admin(message.from_user.id):
    #     await message.answer("❌ У вас немає прав для цієї дії")
    #     return

    await state.set_state(AddTrainingStates.title)
    await message.answer(
        "🏋️ *Створення нового тренування*\n\n"
        "Крок 1/5: Введіть назву тренування:",
        parse_mode="Markdown",
    )


@router.message(AddTrainingStates.title)
async def process_title(message: Message, state: FSMContext) -> None:
    """Process training title."""
    await state.update_data(title=message.text)
    await state.set_state(AddTrainingStates.date)

    calendar_kb = create_calendar()
    await message.answer(
        "📅 Крок 2/5: Оберіть дату тренування:",
        reply_markup=calendar_kb,
    )


# Calendar navigation callbacks
@router.callback_query(F.data.startswith("calendar:"))
async def calendar_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle calendar navigation and date selection."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    _ = await state.get_state()

    action, params = process_calendar_callback(callback.data)

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Створення тренування скасовано")
        await callback.answer()
        return

    if action == "prev":
        year, month = get_prev_month(params["year"], params["month"])
        calendar_kb = create_calendar(year, month)
        await callback.message.edit_reply_markup(reply_markup=calendar_kb)
        await callback.answer()
        return

    if action == "next":
        year, month = get_next_month(params["year"], params["month"])
        calendar_kb = create_calendar(year, month)
        await callback.message.edit_reply_markup(reply_markup=calendar_kb)
        await callback.answer()
        return

    if action == "back":
        calendar_kb = create_calendar(params["year"], params["month"])
        await callback.message.edit_text(
            "📅 Крок 2/5: Оберіть дату тренування:",
            reply_markup=calendar_kb,
        )
        await callback.answer()
        return

    if action == "day":
        selected_date = datetime(params["year"], params["month"], params["day"])
        await state.update_data(selected_date=selected_date)
        await state.set_state(AddTrainingStates.time)

        time_kb = create_time_picker(selected_date)
        await callback.message.edit_text(
            "🕐 Крок 3/5: Оберіть час тренування:",
            reply_markup=time_kb,
        )
        await callback.answer()
        return

    await callback.answer()


# Time selection callbacks
@router.callback_query(F.data.startswith("time:"))
async def time_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle time selection."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    action, params = process_calendar_callback(callback.data)

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Створення тренування скасовано")
        await callback.answer()
        return

    if action == "select":
        scheduled_at = datetime(
            params["year"],
            params["month"],
            params["day"],
            params["hour"],
            params["minute"],
        )
        await state.update_data(scheduled_at=scheduled_at)
        await state.set_state(AddTrainingStates.duration)

        duration_kb = create_duration_picker()
        await callback.message.edit_text(
            "⏱️ Крок 4/5: Оберіть тривалість тренування:",
            reply_markup=duration_kb,
        )
        await callback.answer()
        return

    await callback.answer()


# Duration selection callbacks
@router.callback_query(F.data.startswith("duration:"))
async def duration_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle duration selection."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    parts = callback.data.split(":")
    action = parts[1]

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Створення тренування скасовано")
        await callback.answer()
        return

    duration = int(action)
    await state.update_data(duration=duration)
    await state.set_state(AddTrainingStates.max_participants)

    participants_kb = create_participants_picker()
    await callback.message.edit_text(
        "👥 Крок 5/5: Оберіть максимальну кількість учасників:",
        reply_markup=participants_kb,
    )
    await callback.answer()


# Participants selection callbacks
@router.callback_query(F.data.startswith("participants:"))
async def participants_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle participants selection and create training."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    parts = callback.data.split(":")
    action = parts[1]

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Створення тренування скасовано")
        await callback.answer()
        return

    max_participants = int(action)
    data = await state.get_data()

    async with async_session_maker() as session:
        training_repo = TrainingRepository(session)

        training = await training_repo.create(
            title=data["title"],
            scheduled_at=data["scheduled_at"],
            duration_minutes=data["duration"],
            max_participants=max_participants,
            location=None,
            description=None,
        )

        # Sync with Google Calendar
        try:
            calendar_service = GoogleCalendarService()
            event_id = await calendar_service.create_event(training)
            if event_id:
                await training_repo.update_google_event_id(training.id, event_id)
        except Exception:
            pass  # Don't fail if Google sync fails

        # Add to Google Sheets
        try:
            sheets_service = GoogleSheetsService()
            await sheets_service.add_training_record(training)
        except Exception:
            pass

        await session.commit()

        date_str = training.scheduled_at.strftime("%d.%m.%Y")
        time_str = training.scheduled_at.strftime("%H:%M")

        text = (
            "✅ *Тренування створено!*\n\n"
            f"🏋️ *{training.title}*\n"
            f"📅 Дата: {date_str}\n"
            f"🕐 Час: {time_str}\n"
            f"⏱️ Тривалість: {training.duration_minutes} хв\n"
            f"👥 Місць: {training.max_participants}\n"
        )

        await callback.message.edit_text(text, parse_mode="Markdown")
        await callback.message.answer(
            "Оберіть наступну дію:",
            reply_markup=get_admin_menu_keyboard(),
        )

    await state.clear()
    await callback.answer("✅ Тренування створено!")


# Ignore callback for non-clickable buttons
@router.callback_query(F.data == "ignore")
async def ignore_callback(callback: CallbackQuery) -> None:
    """Ignore callback for non-clickable buttons."""
    await callback.answer()


@router.message(F.text == "📈 Адмін-статистика")
async def statistics_handler(message: Message) -> None:
    """Show statistics for admin.

    Renamed from "📊 Статистика" (GYM-36) — the main menu now has its own
    "📊 Статистика" WebApp button (GYM-18) opening ``/statistics``; keeping
    the same label here would put two unrelated destinations behind one
    caption in the admin keyboard.
    """
    # if not is_admin(message.from_user.id):
    #     await message.answer("❌ У вас немає прав для цієї дії")
    #     return

    async with async_session_maker() as session:
        training_repo = TrainingRepository(session)
        user_repo = UserRepository(session)

        upcoming = await training_repo.get_upcoming(limit=100)
        users = await user_repo.get_all_with_notifications()

        total_bookings = sum(
            len([b for b in t.bookings if b.status == "confirmed"]) for t in upcoming
        )

        text = (
            "📈 *Адмін-статистика*\n\n"
            f"👥 Зареєстрованих користувачів: {len(users)}\n"
            f"📅 Запланованих тренувань: {len(upcoming)}\n"
            f"📝 Активних записів: {total_bookings}\n"
        )

        await message.answer(text, parse_mode="Markdown")


@router.callback_query(F.data.startswith("admin_participants:"))
async def admin_participants_callback(callback: CallbackQuery) -> None:
    """Show training participants for admin."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Немає доступу", show_alert=True)
        return

    training_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        training_repo = TrainingRepository(session)
        booking_repo = BookingRepository(session)

        training = await training_repo.get_by_id(training_id)
        if not training:
            await callback.answer("❌ Тренування не знайдено", show_alert=True)
            return

        bookings = await booking_repo.get_training_participants(training_id)

        date_str = training.scheduled_at.strftime("%d.%m.%Y %H:%M")
        text = f"👥 *Учасники тренування*\n🏋️ {training.title}\n📅 {date_str}\n\n"

        if not bookings:
            text += "_Поки немає записів_"
        else:
            for i, booking in enumerate(bookings, 1):
                user = booking.user
                phone = f" | {user.phone}" if user.phone else ""
                username = f" (@{user.username})" if user.username else ""
                text += f"{i}. {user.full_name}{username}{phone}\n"

        keyboard = get_admin_training_keyboard(training)
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer()


@router.callback_query(F.data.startswith("admin_cancel:"))
async def admin_cancel_training_callback(callback: CallbackQuery) -> None:
    """Cancel training (admin)."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Немає доступу", show_alert=True)
        return

    training_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        training_repo = TrainingRepository(session)
        booking_repo = BookingRepository(session)

        training = await training_repo.get_by_id(training_id)
        if not training:
            await callback.answer("❌ Тренування не знайдено", show_alert=True)
            return

        # Get participants to notify
        _ = await booking_repo.get_training_participants(training_id)

        # Cancel training
        await training_repo.cancel(training_id)

        # Cancel in Google Calendar
        with suppress(Exception):
            if training.google_calendar_event_id:
                calendar_service = GoogleCalendarService()
                await calendar_service.delete_event(training.google_calendar_event_id)

        await session.commit()

        # TODO: Notify participants about cancellation

        await callback.answer("✅ Тренування скасовано", show_alert=True)

        # Show updated schedule
        trainings = await training_repo.get_upcoming(limit=10)
        keyboard = get_schedule_inline_keyboard(trainings)
        await callback.message.edit_text(
            "📅 *Розклад тренувань*\n\nТренування скасовано.",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )


@router.callback_query(F.data == "admin_back")
async def admin_back_callback(callback: CallbackQuery) -> None:
    """Go back to schedule (admin)."""
    if not isinstance(callback.message, Message):
        return

    async with async_session_maker() as session:
        training_repo = TrainingRepository(session)
        trainings = await training_repo.get_upcoming(limit=10)

        keyboard = get_schedule_inline_keyboard(trainings)
        await callback.message.edit_text(
            "📅 *Розклад тренувань*",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        await callback.answer()


@router.message(Command("admin"))
async def admin_command(message: Message) -> None:
    """Show admin menu."""
    if message.from_user is None:
        return

    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас немає прав адміністратора")
        return

    await message.answer(
        "👨‍💼 *Адмін-панель*\n\n"
        "Оберіть дію з меню нижче:",
        reply_markup=get_admin_menu_keyboard(),
        parse_mode="Markdown",
    )
