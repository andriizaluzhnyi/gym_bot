"""Schedule related handlers."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards import get_schedule_inline_keyboard, get_training_detail_keyboard
from src.database.repository import BookingRepository, TrainingRepository
from src.database.session import async_session_maker

router = Router()


@router.message(Command("schedule"))
@router.message(F.text == "📅 Розклад")
async def schedule_handler(message: Message) -> None:
    """Show upcoming trainings schedule."""
    async with async_session_maker() as session:
        training_repo = TrainingRepository(session)
        trainings = await training_repo.get_upcoming(limit=10)

        if not trainings:
            await message.answer(
                "📅 *Розклад тренувань*\n\n"
                "На жаль, наразі немає запланованих тренувань.\n"
                "Слідкуйте за оновленнями!",
                parse_mode="Markdown",
            )
            return

        text = (
            "📅 *Розклад тренувань*\n\n"
            "Оберіть тренування для перегляду деталей або запису:\n\n"
            "✅ — є вільні місця\n"
            "❌ — місць немає"
        )

        keyboard = get_schedule_inline_keyboard(trainings)
        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "back_to_schedule")
async def back_to_schedule_callback(callback: CallbackQuery) -> None:
    """Handle back to schedule button."""
    async with async_session_maker() as session:
        training_repo = TrainingRepository(session)
        trainings = await training_repo.get_upcoming(limit=10)

        text = (
            "📅 *Розклад тренувань*\n\n"
            "Оберіть тренування для перегляду деталей або запису:\n\n"
            "✅ — є вільні місця\n"
            "❌ — місць немає"
        )

        keyboard = get_schedule_inline_keyboard(trainings)
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer()


@router.callback_query(F.data.startswith("training:"))
async def training_detail_callback(callback: CallbackQuery) -> None:
    """Show training details."""
    training_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        training_repo = TrainingRepository(session)
        booking_repo = BookingRepository(session)

        training = await training_repo.get_by_id(training_id)

        if not training:
            await callback.answer("❌ Тренування не знайдено", show_alert=True)
            return

        # Check if user already has a booking
        from src.database.repository import UserRepository

        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(callback.from_user.id)

        user_has_booking = False
        if user:
            existing_booking = await booking_repo.get_user_booking_for_training(
                user.id, training_id
            )
            user_has_booking = existing_booking is not None

        # Format training details
        date_str = training.scheduled_at.strftime("%d.%m.%Y")
        time_str = training.scheduled_at.strftime("%H:%M")
        duration = training.duration_minutes
        spots = training.available_spots
        total_spots = training.max_participants

        status_text = "✅ Ви записані" if user_has_booking else ""
        location_text = f"📍 *Місце:* {training.location}\n" if training.location else ""
        description_text = f"\n_{training.description}_\n" if training.description else ""

        text = (
            f"🏋️ *{training.title}*\n"
            f"{status_text}\n\n"
            f"📅 *Дата:* {date_str}\n"
            f"🕐 *Час:* {time_str}\n"
            f"⏱️ *Тривалість:* {duration} хв\n"
            f"{location_text}"
            f"👥 *Вільних місць:* {spots}/{total_spots}"
            f"{description_text}"
        )

        keyboard = get_training_detail_keyboard(training, user_has_booking)
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer()


@router.callback_query(F.data == "no_trainings")
async def no_trainings_callback(callback: CallbackQuery) -> None:
    """Handle no trainings callback."""
    await callback.answer("Немає доступних тренувань", show_alert=True)
