"""Main bot module."""

import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    MenuButtonWebApp,
    WebAppInfo,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from src.bot.handlers import setup_routers
from src.config import get_settings
from src.database.session import init_db
from src.services.group_reminders import GroupReminderService
from src.services.notifications import NotificationService
from src.webapp.server import start_webapp, stop_webapp

# Load .env file for local development (ignored if not exists)
load_dotenv(Path(__file__).parent.parent.parent / '.env')

settings = get_settings()
logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def _configure_logging() -> None:
    """Apply the application's logging configuration.

    Alembic's ``env.py`` loads ``alembic.ini`` via ``fileConfig``, which
    unconditionally overwrites the root logger's level and handlers
    (forcing the level to WARNING) regardless of ``disable_existing_loggers``.
    Call this again after running migrations to restore INFO-level logging.
    """
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, force=True)


def create_bot() -> Bot:
    """Create and configure the bot instance."""
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )


# Commands visible in every private chat (GYM-36). "/admin" is deliberately
# not here — it's added per-admin below, since Telegram resolves command
# scopes by taking the single most specific match rather than merging them:
# a bare BotCommandScopeChat(chat_id=admin_id, commands=["admin"]) would
# *replace* this list for that admin's chat, not add to it.
_PRIVATE_COMMANDS = [
    BotCommand(command="start", description="Почати роботу з ботом"),
    BotCommand(command="help", description="Довідка"),
    BotCommand(command="nutrition", description="Харчування (Mini App)"),
    BotCommand(command="statistics", description="Статистика тренувань (Mini App)"),
    BotCommand(command="schedule", description="Розклад тренувань"),
    BotCommand(command="my", description="Мої записи"),
]
_ADMIN_COMMAND = BotCommand(command="admin", description="Адмін-панель")


async def configure_bot_commands(bot: Bot) -> None:
    """Register the bot's command list and default chat-menu button once
    at startup (GYM-35/36).

    Commands: the base list for every private chat, plus that same list
    with "/admin" appended for each ``settings.admin_user_ids`` chat
    specifically (see note on ``_PRIVATE_COMMANDS`` above on why it's
    repeated rather than just ``[_ADMIN_COMMAND]``). Group-chat commands
    (e.g. a future ``/reminders``) aren't registered yet — no handler
    exists for them.

    Setting an admin's per-chat commands fails if that admin has never
    opened a chat with the bot (no ``chat_id`` for Telegram to resolve
    yet); logged and skipped rather than aborting the rest of startup.

    Chat-menu button: set globally, with no ``chat_id``, so it applies to
    every private chat that hasn't set its own — unlike the old per-chat
    call previously in ``/start`` (removed in GYM-35), which only reached
    users who ran ``/start`` again after a rename. No-op without
    ``WEBAPP_URL`` configured, same guard as the rest of the WebApp
    integration.
    """
    await bot.set_my_commands(_PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())

    for admin_id in settings.admin_user_ids:
        try:
            await bot.set_my_commands(
                [*_PRIVATE_COMMANDS, _ADMIN_COMMAND],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception as e:
            logger.warning(f"Failed to set admin commands for {admin_id}: {e}")

    if not settings.webapp_url:
        return

    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="📱 Щоденник",
            web_app=WebAppInfo(url=f"{settings.webapp_url}/nutrition"),
        )
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

    # GYM-34: group nutrition/measurements/photo-progress reminders —
    # checked every 5 minutes so a scheduled time is never missed by more
    # than that, without the DB churn of a finer interval.
    group_reminder_service = GroupReminderService(bot)
    scheduler.add_job(
        group_reminder_service.send_due_reminders,
        "interval",
        minutes=5,
        id="group_reminders",
        replace_existing=True,
    )

    return scheduler


async def run_bot() -> None:
    """Run the bot."""
    # Setup logging
    _configure_logging()

    logger.info("Starting bot...")

    # Run Alembic migrations
    try:
        from alembic import command
        from alembic.config import Config
        from pathlib import Path

        alembic_ini = Path(__file__).parent.parent.parent / 'alembic.ini'
        alembic_cfg = Config(str(alembic_ini))
        logger.info("Running database migrations...")
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations completed")
    except Exception as e:
        logger.warning(f"Migration failed, falling back to create_all: {e}")
        # Fallback to simple create_all if migrations fail
        await init_db()
        logger.info("Database initialized via create_all")
    finally:
        # alembic.ini's fileConfig (loaded by alembic/env.py) overwrites the
        # root logger's level/handlers; restore the app's own configuration.
        _configure_logging()

    # Create bot and dispatcher
    bot = create_bot()
    dp = Dispatcher()

    # Set bot instance for webapp
    from src.webapp.server import set_bot_instance, set_bot_username
    set_bot_instance(bot)

    # GYM-34: cache the bot's own @username once — group reminder deep
    # links (`https://t.me/<bot>?start=...`) need it, and re-fetching via
    # get_me() on every reminder send would be wasteful.
    try:
        bot_info = await bot.get_me()
        set_bot_username(bot_info.username)
    except Exception as e:
        logger.warning(f"Failed to fetch bot username via get_me(): {e}")

    # Register command list and the default chat-menu button (GYM-35/36)
    await configure_bot_commands(bot)

    # Setup routers
    main_router = setup_routers()
    dp.include_router(main_router)

    # Setup scheduler
    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Scheduler started")

    # Start web server for Mini App
    webapp_runner = None
    if settings.webapp_url:
        webapp_runner = await start_webapp(port=settings.webapp_port)
        logger.info(f"Web server started on port {settings.webapp_port}")

    # Start polling
    try:
        logger.info("Bot started polling")
        await dp.start_polling(
            bot, allowed_updates=dp.resolve_used_update_types()
        )
    finally:
        scheduler.shutdown()
        if webapp_runner:
            await stop_webapp(webapp_runner)
        await bot.session.close()
        logger.info("Bot stopped")


def main() -> None:
    """Entry point for the bot."""
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
