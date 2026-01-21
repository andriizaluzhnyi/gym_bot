"""Admin handlers for managing trainings."""

from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

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
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас немає прав для цієї дії")
        return

    await state.set_state(AddTrainingStates.title)
    await message.answer(
        "🏋️ *Створення нового тренування*\n\n"
        "Крок 1/7: Введіть назву тренування:",
        parse_mode="Markdown",
    )


@router.message(AddTrainingStates.title)
async def process_title(message: Message, state: FSMContext) -> None:
    """Process training title."""
    await state.update_data(title=message.text)
    await state.set_state(AddTrainingStates.date)
    await message.answer(
        "📅 Крок 2/7: Введіть дату тренування\n"
        "Формат: ДД.ММ.РРРР (наприклад, 25.01.2025):"
    )


@router.message(AddTrainingStates.date)
async def process_date(message: Message, state: FSMContext) -> None:
    """Process training date."""
    try:
        date = datetime.strptime(message.text.strip(), "%d.%m.%Y")
        await state.update_data(date=date)
        await state.set_state(AddTrainingStates.time)
        await message.answer("🕐 Крок 3/7: Введіть час тренування\nФормат: ГГ:ХХ (наприклад, 18:30):")
    except ValueError:
        await message.answer("❌ Неправильний формат дати. Спробуйте ще раз (ДД.ММ.РРРР):")


@router.message(AddTrainingStates.time)
async def process_time(message: Message, state: FSMContext) -> None:
    """Process training time."""
    try:
        time_parts = message.text.strip().split(":")
        hour = int(time_parts[0])
        minute = int(time_parts[1])

        data = await state.get_data()
        scheduled_at = data["date"].replace(hour=hour, minute=minute)
        await state.update_data(scheduled_at=scheduled_at)
        await state.set_state(AddTrainingStates.duration)
        await message.answer(
            "⏱️ Крок 4/7: Введіть тривалість тренування в хвилинах\n(наприклад, 60):"
        )
    except (ValueError, IndexError):
        await message.answer("❌ Неправильний формат часу. Спробуйте ще раз (ГГ:ХХ):")


@router.message(AddTrainingStates.duration)
async def process_duration(message: Message, state: FSMContext) -> None:
    """Process training duration."""
    try:
        duration = int(message.text.strip())
        if duration <= 0 or duration > 480:
            raise ValueError("Invalid duration")
        await state.update_data(duration=duration)
        await state.set_state(AddTrainingStates.max_participants)
        await message.answer("👥 Крок 5/7: Введіть максимальну кількість учасників:")
    except ValueError:
        await message.answer("❌ Введіть коректне число від 1 до 480:")


@router.message(AddTrainingStates.max_participants)
async def process_max_participants(message: Message, state: FSMContext) -> None:
    """Process max participants."""
    try:
        max_p = int(message.text.strip())
        if max_p <= 0 or max_p > 100:
            raise ValueError("Invalid number")
        await state.update_data(max_participants=max_p)
        await state.set_state(AddTrainingStates.location)
        await message.answer(
            "📍 Крок 6/7: Введіть місце проведення\n(або надішліть '-' щоб пропустити):"
        )
    except ValueError:
        await message.answer("❌ Введіть коректне число від 1 до 100:")


@router.message(AddTrainingStates.location)
async def process_location(message: Message, state: FSMContext) -> None:
    """Process training location."""
    location = message.text.strip() if message.text.strip() != "-" else None
    await state.update_data(location=location)
    await state.set_state(AddTrainingStates.description)
    await message.answer(
        "📝 Крок 7/7: Введіть опис тренування\n(або надішліть '-' щоб пропустити):"
    )


@router.message(AddTrainingStates.description)
async def process_description(message: Message, state: FSMContext) -> None:
    """Process training description and create training."""
    description = message.text.strip() if message.text.strip() != "-" else None
    data = await state.get_data()

    async with async_session_maker() as session:
        training_repo = TrainingRepository(session)

        training = await training_repo.create(
            title=data["title"],
            scheduled_at=data["scheduled_at"],
            duration_minutes=data["duration"],
            max_participants=data["max_participants"],
            location=data.get("location"),
            description=description,
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

        if training.location:
            text += f"📍 Місце: {training.location}\n"

        await message.answer(text, reply_markup=get_admin_menu_keyboard(), parse_mode="Markdown")

    await state.clear()


@router.message(F.text == "📊 Статистика")
async def statistics_handler(message: Message) -> None:
    """Show statistics for admin."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас немає прав для цієї дії")
        return

    async with async_session_maker() as session:
        training_repo = TrainingRepository(session)
        user_repo = UserRepository(session)

        upcoming = await training_repo.get_upcoming(limit=100)
        users = await user_repo.get_all_with_notifications()

        total_bookings = sum(
            len([b for b in t.bookings if b.status == "confirmed"]) for t in upcoming
        )

        text = (
            "📊 *Статистика*\n\n"
            f"👥 Зареєстрованих користувачів: {len(users)}\n"
            f"📅 Запланованих тренувань: {len(upcoming)}\n"
            f"📝 Активних записів: {total_bookings}\n"
        )

        await message.answer(text, parse_mode="Markdown")


@router.callback_query(F.data.startswith("admin_participants:"))
async def admin_participants_callback(callback: CallbackQuery) -> None:
    """Show training participants for admin."""
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
        bookings = await booking_repo.get_training_participants(training_id)

        # Cancel training
        await training_repo.cancel(training_id)

        # Cancel in Google Calendar
        try:
            if training.google_calendar_event_id:
                calendar_service = GoogleCalendarService()
                await calendar_service.delete_event(training.google_calendar_event_id)
        except Exception:
            pass

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
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас немає прав адміністратора")
        return

    await message.answer(
        "👨‍💼 *Адмін-панель*\n\n"
        "Оберіть дію з меню нижче:",
        reply_markup=get_admin_menu_keyboard(),
        parse_mode="Markdown",
    )
