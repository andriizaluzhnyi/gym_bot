"""Main bot module."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.bot.handlers import setup_routers
from src.config import get_settings
from src.database.session import init_db
from src.services.notifications import NotificationService

settings = get_settings()
logger = logging.getLogger(__name__)


def create_bot() -> Bot:
    """Create and configure the bot instance."""
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    """Setup the scheduler for reminder notifications."""
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    notification_service = NotificationService(bot)

    # Schedule 24-hour reminder check (runs every 30 minutes)
    scheduler.add_job(
        notification_service.process_reminders,
        "interval",
        minutes=30,
        args=[24],
        id="reminder_24h",
        replace_existing=True,
    )

    # Schedule 2-hour reminder check (runs every 15 minutes)
    scheduler.add_job(
        notification_service.process_reminders,
        "interval",
        minutes=15,
        args=[2],
        id="reminder_2h",
        replace_existing=True,
    )

    return scheduler


async def run_bot() -> None:
    """Run the bot."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("Starting bot...")

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Create bot and dispatcher
    bot = create_bot()
    dp = Dispatcher()

    # Setup routers
    main_router = setup_routers()
    dp.include_router(main_router)

    # Setup scheduler
    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Scheduler started")

    # Start polling
    try:
        logger.info("Bot started polling")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Bot stopped")


def main() -> None:
    """Entry point for the bot."""
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
