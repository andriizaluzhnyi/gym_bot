"""Start and help command handlers."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from src.bot.keyboards import get_admin_menu_keyboard, get_main_menu_keyboard
from src.config import get_settings
from src.database.repository import UserRepository
from src.database.session import async_session_maker

router = Router()
settings = get_settings()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Handle /start command."""
    if message.from_user is None:
        return

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
        "Я допоможу тобі з харчуванням і тренуваннями:\n\n"
        "🍎 *Харчування* — щоденник калорій, БЖУ та води\n"
        "🏋️ *Тренування* — лог підходів за твоєю програмою\n"
        "📊 *Статистика* — прогрес, рекорди, серія тренувань\n"
        "👤 *Профіль* — особисті дані та цілі\n\n"
        "А ще можна записатися на групові заняття:\n"
        "📅 *Розклад* — доступні тренування\n"
        "📝 *Мої записи* — твої записи на заняття\n\n"
        "Обирай дію з меню нижче 👇"
    )

    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="Markdown")


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Допомога")
async def cmd_help(message: Message) -> None:
    """Handle /help command."""
    help_text = (
        "📚 *Інструкція з використання бота*\n\n"
        "*Команди:*\n"
        "/start — почати роботу з ботом\n"
        "/help — показати цю довідку\n"
        "/nutrition — харчування (Mini App)\n"
        "/statistics — статистика тренувань (Mini App)\n"
        "/schedule — розклад тренувань\n"
        "/my — мої записи\n\n"
        "*Розділи:*\n"
        "🍎 *Харчування* — калорії, БЖУ та вода за сьогодні, тренди за "
        "тиждень/місяць\n"
        "🏋️ *Тренування* — лог підходів за програмою дня\n"
        "📊 *Статистика* — об'єм, рекорди, історія, серія тренувань\n"
        "👤 *Профіль* — особисті дані, денні цілі, налаштування\n\n"
        "*Як записатися на групове заняття:*\n"
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
    if message.contact is None or message.from_user is None:
        return

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
