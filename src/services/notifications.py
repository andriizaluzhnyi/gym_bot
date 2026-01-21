"""Notification service for sending reminders."""

from datetime import datetime, timedelta

from aiogram import Bot

from src.config import get_settings
from src.database.models import BookingStatus
from src.database.repository import BookingRepository, TrainingRepository
from src.database.session import async_session_maker

settings = get_settings()


class NotificationService:
    """Service for sending notification reminders."""

    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_reminder(
        self,
        telegram_id: int,
        training_title: str,
        training_time: datetime,
        hours_before: int,
    ) -> bool:
        """Send a reminder to a user.

        Args:
            telegram_id: User's Telegram ID
            training_title: Training title
            training_time: Training scheduled time
            hours_before: Hours before training

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            date_str = training_time.strftime("%d.%m.%Y")
            time_str = training_time.strftime("%H:%M")

            if hours_before >= 24:
                time_text = "завтра"
            elif hours_before >= 2:
                time_text = f"через {hours_before} години"
            else:
                time_text = "скоро"

            text = (
                f"🔔 *Нагадування про тренування!*\n\n"
                f"🏋️ *{training_title}*\n"
                f"📅 {date_str} о {time_str}\n\n"
                f"Тренування {time_text}!\n"
                f"Не забудьте підготуватися 💪"
            )

            await self.bot.send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode="Markdown",
            )
            return True

        except Exception as e:
            print(f"Error sending reminder to {telegram_id}: {e}")
            return False

    async def process_reminders(self, hours_before: int) -> int:
        """Process and send reminders for trainings.

        Args:
            hours_before: Hours before training to send reminder

        Returns:
            Number of reminders sent
        """
        reminder_field = "reminder_24h_sent" if hours_before >= 24 else "reminder_2h_sent"
        sent_count = 0

        async with async_session_maker() as session:
            training_repo = TrainingRepository(session)
            booking_repo = BookingRepository(session)

            # Get trainings in the reminder window
            now = datetime.utcnow()
            target_time = now + timedelta(hours=hours_before)
            window_start = target_time - timedelta(minutes=30)
            window_end = target_time + timedelta(minutes=30)

            trainings = await training_repo.get_trainings_for_reminder(
                hours_before, reminder_field
            )

            for training in trainings:
                # Skip if training is in the past or cancelled
                if training.scheduled_at < now or training.is_cancelled:
                    continue

                # Check if training is within the reminder window
                if not (window_start <= training.scheduled_at <= window_end):
                    continue

                # Get confirmed bookings
                for booking in training.bookings:
                    if booking.status != BookingStatus.CONFIRMED.value:
                        continue

                    # Check if reminder already sent
                    if hours_before >= 24 and booking.reminder_24h_sent:
                        continue
                    if hours_before < 24 and booking.reminder_2h_sent:
                        continue

                    # Check if user has notifications enabled
                    user = booking.user
                    if not user.notifications_enabled:
                        continue

                    # Send reminder
                    success = await self.send_reminder(
                        telegram_id=user.telegram_id,
                        training_title=training.title,
                        training_time=training.scheduled_at,
                        hours_before=hours_before,
                    )

                    if success:
                        # Mark reminder as sent
                        reminder_type = "24h" if hours_before >= 24 else "2h"
                        await booking_repo.mark_reminder_sent(booking.id, reminder_type)
                        sent_count += 1

            await session.commit()

        return sent_count

    async def send_training_cancelled_notification(
        self,
        telegram_id: int,
        training_title: str,
        training_time: datetime,
    ) -> bool:
        """Send notification about cancelled training.

        Args:
            telegram_id: User's Telegram ID
            training_title: Training title
            training_time: Original training time

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            date_str = training_time.strftime("%d.%m.%Y")
            time_str = training_time.strftime("%H:%M")

            text = (
                f"❌ *Тренування скасовано*\n\n"
                f"🏋️ *{training_title}*\n"
                f"📅 {date_str} о {time_str}\n\n"
                f"На жаль, це тренування було скасовано.\n"
                f"Перевірте розклад для запису на інше тренування."
            )

            await self.bot.send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode="Markdown",
            )
            return True

        except Exception as e:
            print(f"Error sending cancellation notification to {telegram_id}: {e}")
            return False

    async def send_booking_confirmation(
        self,
        telegram_id: int,
        training_title: str,
        training_time: datetime,
    ) -> bool:
        """Send booking confirmation.

        Args:
            telegram_id: User's Telegram ID
            training_title: Training title
            training_time: Training time

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            date_str = training_time.strftime("%d.%m.%Y")
            time_str = training_time.strftime("%H:%M")

            text = (
                f"✅ *Запис підтверджено!*\n\n"
                f"🏋️ *{training_title}*\n"
                f"📅 {date_str} о {time_str}\n\n"
                f"До зустрічі на тренуванні! 💪"
            )

            await self.bot.send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode="Markdown",
            )
            return True

        except Exception as e:
            print(f"Error sending confirmation to {telegram_id}: {e}")
            return False
