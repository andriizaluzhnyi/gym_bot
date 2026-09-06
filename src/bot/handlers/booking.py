"""Booking related handlers."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards import (
    get_booking_confirmation_keyboard,
    get_confirm_cancel_keyboard,
    get_my_bookings_keyboard,
    get_training_detail_keyboard,
)
from src.database.repository import BookingRepository, TrainingRepository, UserRepository
from src.database.session import async_session_maker
from src.services.google_sheets import GoogleSheetsService

router = Router()


@router.message(Command("my"))
@router.message(F.text == "📝 Мої записи")
async def my_bookings_handler(message: Message) -> None:
    """Show user's upcoming bookings."""
    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        booking_repo = BookingRepository(session)

        user = await user_repo.get_by_telegram_id(message.from_user.id)
        if not user:
            await message.answer("❌ Спочатку натисніть /start")
            return

        bookings = await booking_repo.get_user_upcoming_bookings(user.id)

        if not bookings:
            text = (
                "📝 *Мої записи*\n\n"
                "У вас поки немає активних записів.\n"
                "Перейдіть до розкладу, щоб записатися на тренування!"
            )
        else:
            text = (
                "📝 *Мої записи*\n\n"
                "Ваші активні записи на тренування:\n"
                "Натисніть на запис для детальної інформації."
            )

        keyboard = get_my_bookings_keyboard(bookings)
        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data.startswith("book:"))
async def book_training_callback(callback: CallbackQuery) -> None:
    """Handle booking request."""
    training_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        training_repo = TrainingRepository(session)
        booking_repo = BookingRepository(session)

        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("❌ Спочатку натисніть /start", show_alert=True)
            return

        training = await training_repo.get_by_id(training_id)
        if not training:
            await callback.answer("❌ Тренування не знайдено", show_alert=True)
            return

        # Check if already booked
        existing = await booking_repo.get_user_booking_for_training(user.id, training_id)
        if existing:
            await callback.answer("❌ Ви вже записані на це тренування", show_alert=True)
            return

        # Check available spots
        if training.is_full:
            await callback.answer("❌ На жаль, вільних місць немає", show_alert=True)
            return

        # Create booking
        booking = await booking_repo.create(user.id, training_id)
        await session.commit()

        # Sync with Google services (async, don't block)
        try:
            sheets_service = GoogleSheetsService()
            await sheets_service.add_booking_record(booking, user, training)
        except Exception:
            pass  # Don't fail booking if Google sync fails

        date_str = training.scheduled_at.strftime("%d.%m.%Y")
        time_str = training.scheduled_at.strftime("%H:%M")

        text = (
            "✅ *Ви успішно записані!*\n\n"
            f"🏋️ *{training.title}*\n"
            f"📅 Дата: {date_str}\n"
            f"🕐 Час: {time_str}\n\n"
            "🔔 Ви отримаєте нагадування:\n"
            "• За 24 години до тренування\n"
            "• За 2 години до тренування"
        )

        keyboard = get_booking_confirmation_keyboard(booking.id)
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer("✅ Успішно записано!")


@router.callback_query(F.data.startswith("cancel_booking:"))
async def cancel_booking_from_training_callback(callback: CallbackQuery) -> None:
    """Handle cancel booking request from training detail."""
    training_id = int(callback.data.split(":")[1])

    text = (
        "⚠️ *Підтвердження скасування*\n\n"
        "Ви впевнені, що хочете скасувати запис на це тренування?"
    )

    keyboard = get_confirm_cancel_keyboard(training_id)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_cancel:"))
async def confirm_cancel_callback(callback: CallbackQuery) -> None:
    """Confirm booking cancellation."""
    training_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        booking_repo = BookingRepository(session)
        training_repo = TrainingRepository(session)

        user = await user_repo.get_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("❌ Помилка", show_alert=True)
            return

        booking = await booking_repo.get_user_booking_for_training(user.id, training_id)
        if not booking:
            await callback.answer("❌ Запис не знайдено", show_alert=True)
            return

        training = await training_repo.get_by_id(training_id)

        await booking_repo.cancel(booking.id)
        await session.commit()

        # Sync with Google services
        try:
            sheets_service = GoogleSheetsService()
            await sheets_service.update_booking_status(booking.id, "cancelled")
        except Exception:
            pass

        date_str = training.scheduled_at.strftime("%d.%m.%Y") if training else ""
        time_str = training.scheduled_at.strftime("%H:%M") if training else ""
        title = training.title if training else "Тренування"

        text = (
            "❌ *Запис скасовано*\n\n"
            f"🏋️ {title}\n"
            f"📅 {date_str} о {time_str}\n\n"
            "Ви можете записатися на інше тренування у розкладі."
        )

        from src.bot.keyboards import get_schedule_inline_keyboard

        trainings = await training_repo.get_upcoming(limit=10)
        keyboard = get_schedule_inline_keyboard(trainings)

        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer("Запис скасовано")


@router.callback_query(F.data.startswith("cancel_booking_id:"))
async def cancel_booking_by_id_callback(callback: CallbackQuery) -> None:
    """Cancel booking by booking ID."""
    booking_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        booking_repo = BookingRepository(session)
        training_repo = TrainingRepository(session)

        booking = await booking_repo.get_by_id(booking_id)
        if not booking:
            await callback.answer("❌ Запис не знайдено", show_alert=True)
            return

        training = booking.training
        await booking_repo.cancel(booking_id)
        await session.commit()

        text = (
            "❌ *Запис скасовано*\n\n"
            f"🏋️ {training.title}\n\n"
            "Ви можете записатися на інше тренування у розкладі."
        )

        from src.bot.keyboards import get_schedule_inline_keyboard

        trainings = await training_repo.get_upcoming(limit=10)
        keyboard = get_schedule_inline_keyboard(trainings)

        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer("Запис скасовано")


@router.callback_query(F.data.startswith("my_booking:"))
async def my_booking_detail_callback(callback: CallbackQuery) -> None:
    """Show booking detail from my bookings list."""
    booking_id = int(callback.data.split(":")[1])

    async with async_session_maker() as session:
        booking_repo = BookingRepository(session)
        booking = await booking_repo.get_by_id(booking_id)

        if not booking:
            await callback.answer("❌ Запис не знайдено", show_alert=True)
            return

        training = booking.training

        date_str = training.scheduled_at.strftime("%d.%m.%Y")
        time_str = training.scheduled_at.strftime("%H:%M")
        location_text = f"📍 *Місце:* {training.location}\n" if training.location else ""

        text = (
            f"🏋️ *{training.title}*\n"
            f"✅ Ви записані\n\n"
            f"📅 *Дата:* {date_str}\n"
            f"🕐 *Час:* {time_str}\n"
            f"⏱️ *Тривалість:* {training.duration_minutes} хв\n"
            f"{location_text}"
        )

        keyboard = get_training_detail_keyboard(training, user_has_booking=True)
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer()


@router.callback_query(F.data == "no_bookings")
async def no_bookings_callback(callback: CallbackQuery) -> None:
    """Handle no bookings callback."""
    await callback.answer("У вас немає активних записів", show_alert=True)
