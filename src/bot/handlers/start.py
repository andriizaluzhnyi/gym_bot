"""Start and help command handlers."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import MenuButtonWebApp, Message, WebAppInfo

from src.bot.keyboards import get_admin_menu_keyboard, get_main_menu_keyboard
from src.config import get_settings
from src.database.repository import UserRepository
from src.database.session import async_session_maker

router = Router()
settings = get_settings()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Handle /start command."""
    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user, is_new = await user_repo.get_or_create(
            telegram_id=message.from_user.id,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            username=message.from_user.username,
        )

        # Check if user is admin
        if message.from_user.id in settings.admin_user_ids:
            await user_repo.set_admin(message.from_user.id, True)
            keyboard = get_admin_menu_keyboard()
        else:
            keyboard = get_main_menu_keyboard()

        await session.commit()

    welcome_text = (
        f"👋 Привіт, {message.from_user.first_name}!\n\n"
        "Я бот для запису на тренування. Ось що я вмію:\n\n"
        "📅 *Розклад* — переглянути доступні тренування\n"
        "📝 *Мої записи* — переглянути свої записи\n"
        "👤 *Профіль* — налаштування профілю\n"
        "ℹ️ *Допомога* — інструкція з використання\n\n"
        "Обирай дію з меню нижче 👇"
    )

    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="Markdown")

    if settings.webapp_url:
        await message.bot.set_chat_menu_button(
            chat_id=message.chat.id,
            menu_button=MenuButtonWebApp(
                text="🍎 БЖУ",
                web_app=WebAppInfo(url=f"{settings.webapp_url}/nutrition")
            )
        )


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Допомога")
async def cmd_help(message: Message) -> None:
    """Handle /help command."""
    help_text = (
        "📚 *Інструкція з використання бота*\n\n"
        "*Основні команди:*\n"
        "/start — почати роботу з ботом\n"
        "/help — показати цю довідку\n"
        "/schedule — переглянути розклад тренувань\n"
        "/my — переглянути мої записи\n"
        "/profile — налаштування профілю\n\n"
        "*Як записатися на тренування:*\n"
        "1. Натисни '📅 Розклад'\n"
        "2. Обери тренування зі списку\n"
        "3. Натисни '✅ Записатися'\n\n"
        "*Як скасувати запис:*\n"
        "1. Натисни '📝 Мої записи'\n"
        "2. Обери потрібний запис\n"
        "3. Натисни '❌ Скасувати запис'\n\n"
        "🔔 *Нагадування:*\n"
        "Бот надішле нагадування за 24 години та за 2 години до тренування."
    )

    await message.answer(help_text, parse_mode="Markdown")


@router.message(F.contact)
async def contact_handler(message: Message) -> None:
    """Handle contact sharing."""
    if message.contact.user_id != message.from_user.id:
        await message.answer("❌ Будь ласка, поділіться своїм контактом")
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user = await user_repo.update_phone(
            message.from_user.id,
            message.contact.phone_number,
        )
        await session.commit()

        if user:
            await message.answer(
                f"✅ Номер телефону оновлено: {message.contact.phone_number}",
                reply_markup=get_main_menu_keyboard(),
            )
        else:
            await message.answer("❌ Помилка оновлення профілю")
