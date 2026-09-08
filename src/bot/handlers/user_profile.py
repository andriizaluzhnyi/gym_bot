"""Profile handlers with nutrition settings."""

from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from src.config import get_settings
from src.database.models import Gender
from src.database.repository import UserRepository
from src.database.session import async_session_maker

router = Router()
settings = get_settings()


class ProfileSettingsStates(StatesGroup):
    """States for editing profile settings."""

    edit_age = State()
    edit_height = State()
    edit_weight = State()
    edit_gender = State()
    edit_water = State()
    edit_calories = State()
    edit_protein = State()
    edit_fats = State()
    edit_carbs = State()


def get_profile_settings_keyboard() -> InlineKeyboardMarkup:
    """Get inline keyboard for profile settings (GYM-35).

    The second button opens the WebApp directly via a ``web_app`` inline
    button when ``WEBAPP_URL`` is configured (works in private chats,
    unlike the reply-keyboard chat-menu button); without it, falls back to
    a callback that tells the user the WebApp isn't set up
    (``open_webapp_callback``).
    """
    buttons = [
        [InlineKeyboardButton(text="🎯 Цілі харчування", callback_data="profile:edit_nutrition")],
    ]
    if settings.webapp_url:
        buttons.append([
            InlineKeyboardButton(
                text="📱 Відкрити щоденник",
                web_app=WebAppInfo(url=f"{settings.webapp_url}/nutrition"),
            )
        ])
    else:
        buttons.append([
            InlineKeyboardButton(text="📱 Відкрити щоденник", callback_data="profile:open_webapp")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_nutrition_settings_keyboard(
    water_tracking_enabled: bool = True,
) -> InlineKeyboardMarkup:
    """Get inline keyboard for nutrition settings.

    GYM-25: while water tracking is off, the water button offers to turn
    it back on (``edit:water_toggle``) instead of jumping straight to
    "enter a new goal" for a card the user has hidden.
    """
    water_button = (
        InlineKeyboardButton(text="💧 Денна норма води", callback_data="edit:water")
        if water_tracking_enabled
        else InlineKeyboardButton(
            text="💧 Увімкнути відстеження води", callback_data="edit:water_toggle"
        )
    )
    buttons = [
        [
            InlineKeyboardButton(text="🎂 Вік", callback_data="edit:age"),
            InlineKeyboardButton(text="📏 Зріст", callback_data="edit:height"),
        ],
        [
            InlineKeyboardButton(text="⚖️ Вага", callback_data="edit:weight"),
            InlineKeyboardButton(text="👤 Стать", callback_data="edit:gender"),
        ],
        [water_button],
        [InlineKeyboardButton(text="🔥 Денна норма калорій", callback_data="edit:calories")],
        [
            InlineKeyboardButton(text="🥩 Білки", callback_data="edit:protein"),
            InlineKeyboardButton(text="🧈 Жири", callback_data="edit:fats"),
            InlineKeyboardButton(text="🍞 Вуглеводи", callback_data="edit:carbs"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="edit:back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_gender_keyboard() -> InlineKeyboardMarkup:
    """Get inline keyboard for gender selection."""
    buttons = [
        [
            InlineKeyboardButton(text="👨 Чоловік", callback_data="gender:male"),
            InlineKeyboardButton(text="👩 Жінка", callback_data="gender:female"),
        ],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="gender:cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Get cancel keyboard."""
    buttons = [
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_edit")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _format_nutrition_settings(nutrition: dict[str, Any]) -> str:
    """Format nutrition settings for display."""
    gender_value = nutrition.get("gender")
    gender_text = (
        {
            Gender.MALE.value: "👨 Чоловік",
            Gender.FEMALE.value: "👩 Жінка",
        }.get(gender_value, "не вказано")
        if isinstance(gender_value, str)
        else "не вказано"
    )

    age = nutrition.get("age")
    height = nutrition.get("height")
    weight = nutrition.get("weight")

    # GYM-25: "вимкнено" instead of a goal nobody's tracking toward.
    water_line = (
        f"💧 Вода: {nutrition['daily_water_ml']} мл\n"
        if nutrition.get("water_tracking_enabled", True)
        else "💧 Вода: вимкнено\n"
    )

    return (
        "🎯 *Цілі харчування*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Особисті дані:*\n"
        f"🎂 Вік: {age if age else 'не вказано'} р.\n"
        f"📏 Зріст: {height if height else 'не вказано'} см\n"
        f"⚖️ Вага: {weight if weight else 'не вказано'} кг\n"
        f"👤 Стать: {gender_text}\n\n"
        "*Денні норми:*\n"
        f"{water_line}"
        f"🔥 Калорії: {nutrition['daily_calories']} ккал\n"
        f"🥩 Білки: {nutrition['daily_protein']} г\n"
        f"🧈 Жири: {nutrition['daily_fats']} г\n"
        f"🍞 Вуглеводи: {nutrition['daily_carbs']} г"
    )


@router.message(F.text == "👤 Профіль")
async def profile_handler(message: Message) -> None:
    """Handle profile button with nutrition settings."""
    if message.from_user is None:
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(message.from_user.id)

        if not user:
            await message.answer("❌ Профіль не знайдено. Натисніть /start")
            return

        phone_text = user.phone if user.phone else "не вказано"
        notifications_text = "увімкнені ✅" if user.notifications_enabled else "вимкнені ❌"

        profile_text = (
            f"👤 *Ваш профіль*\n\n"
            f"*Ім'я:* {user.full_name}\n"
            f"*Username:* @{user.username or 'не вказано'}\n"
            f"*Телефон:* {phone_text}\n"
            f"*Сповіщення:* {notifications_text}\n\n"
            f"_Для оновлення телефону надішліть контакт_"
        )

        keyboard = get_profile_settings_keyboard()
        await message.answer(profile_text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "profile:edit_nutrition")
async def show_nutrition_settings(callback: CallbackQuery) -> None:
    """Show nutrition settings."""
    if not isinstance(callback.message, Message):
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        nutrition = await user_repo.get_nutrition_settings(callback.from_user.id)

        if not nutrition:
            await callback.message.edit_text("❌ Профіль не знайдено")
            await callback.answer()
            return

        text = _format_nutrition_settings(nutrition)
        keyboard = get_nutrition_settings_keyboard(nutrition["water_tracking_enabled"])
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer()


@router.callback_query(F.data == "profile:open_webapp")
async def open_webapp_callback(callback: CallbackQuery) -> None:
    """Fallback shown only when WEBAPP_URL isn't configured.

    ``get_profile_settings_keyboard`` gives this button real
    ``callback_data`` only in that case — when a URL is set, it's a
    ``web_app`` button instead and this handler never fires.
    """
    await callback.answer("Web App не налаштований", show_alert=True)


@router.callback_query(F.data == "edit:back")
async def back_to_profile(callback: CallbackQuery, state: FSMContext) -> None:
    """Go back to profile."""
    if not isinstance(callback.message, Message):
        return

    await state.clear()
    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_telegram_id(callback.from_user.id)

        if not user:
            await callback.message.edit_text("❌ Профіль не знайдено")
            await callback.answer()
            return

        phone_text = user.phone if user.phone else "не вказано"
        notifications_text = "увімкнені ✅" if user.notifications_enabled else "вимкнені ❌"

        profile_text = (
            f"👤 *Ваш профіль*\n\n"
            f"*Ім'я:* {user.full_name}\n"
            f"*Username:* @{user.username or 'не вказано'}\n"
            f"*Телефон:* {phone_text}\n"
            f"*Сповіщення:* {notifications_text}\n\n"
            f"_Для оновлення телефону надішліть контакт_"
        )

        keyboard = get_profile_settings_keyboard()
        await callback.message.edit_text(profile_text, reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer()


@router.callback_query(F.data == "cancel_edit")
async def cancel_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel current edit operation."""
    await state.clear()
    await show_nutrition_settings(callback)


# Edit handlers for each field
@router.callback_query(F.data == "edit:age")
async def start_edit_age(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing age."""
    if not isinstance(callback.message, Message):
        return

    await state.set_state(ProfileSettingsStates.edit_age)
    await callback.message.edit_text(
        "🎂 *Введіть ваш вік (число від 10 до 100):*",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(ProfileSettingsStates.edit_age)
async def process_edit_age(message: Message, state: FSMContext) -> None:
    """Process age input."""
    if message.from_user is None or message.text is None:
        return

    try:
        age = int(message.text.strip())
        if not 10 <= age <= 100:
            raise ValueError("Age out of range")
    except ValueError:
        await message.answer("❌ Введіть число від 10 до 100")
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        await user_repo.update_nutrition_settings(message.from_user.id, age=age)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Вік оновлено: {age} р.")

    # Show nutrition settings
    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        nutrition = await user_repo.get_nutrition_settings(message.from_user.id)
        if nutrition is None:
            return
        text = _format_nutrition_settings(nutrition)
        keyboard = get_nutrition_settings_keyboard(nutrition["water_tracking_enabled"])
        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "edit:height")
async def start_edit_height(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing height."""
    if not isinstance(callback.message, Message):
        return

    await state.set_state(ProfileSettingsStates.edit_height)
    await callback.message.edit_text(
        "📏 *Введіть ваш зріст в см (число від 100 до 250):*",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(ProfileSettingsStates.edit_height)
async def process_edit_height(message: Message, state: FSMContext) -> None:
    """Process height input."""
    if message.from_user is None or message.text is None:
        return

    try:
        height = float(message.text.strip().replace(",", "."))
        if not 100 <= height <= 250:
            raise ValueError("Height out of range")
    except ValueError:
        await message.answer("❌ Введіть число від 100 до 250")
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        await user_repo.update_nutrition_settings(message.from_user.id, height=height)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Зріст оновлено: {height} см")

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        nutrition = await user_repo.get_nutrition_settings(message.from_user.id)
        if nutrition is None:
            return
        text = _format_nutrition_settings(nutrition)
        keyboard = get_nutrition_settings_keyboard(nutrition["water_tracking_enabled"])
        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "edit:weight")
async def start_edit_weight(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing weight."""
    if not isinstance(callback.message, Message):
        return

    await state.set_state(ProfileSettingsStates.edit_weight)
    await callback.message.edit_text(
        "⚖️ *Введіть вашу вагу в кг (число від 30 до 300):*",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(ProfileSettingsStates.edit_weight)
async def process_edit_weight(message: Message, state: FSMContext) -> None:
    """Process weight input."""
    if message.from_user is None or message.text is None:
        return

    try:
        weight = float(message.text.strip().replace(",", "."))
        if not 30 <= weight <= 300:
            raise ValueError("Weight out of range")
    except ValueError:
        await message.answer("❌ Введіть число від 30 до 300")
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        await user_repo.update_nutrition_settings(message.from_user.id, weight=weight)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Вагу оновлено: {weight} кг")

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        nutrition = await user_repo.get_nutrition_settings(message.from_user.id)
        if nutrition is None:
            return
        text = _format_nutrition_settings(nutrition)
        keyboard = get_nutrition_settings_keyboard(nutrition["water_tracking_enabled"])
        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "edit:gender")
async def start_edit_gender(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing gender."""
    if not isinstance(callback.message, Message):
        return

    await state.set_state(ProfileSettingsStates.edit_gender)
    await callback.message.edit_text(
        "👤 *Оберіть стать:*",
        reply_markup=get_gender_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gender:"))
async def process_edit_gender(callback: CallbackQuery, state: FSMContext) -> None:
    """Process gender selection."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    action = callback.data.split(":")[1]

    if action == "cancel":
        await state.clear()
        await show_nutrition_settings(callback)
        return

    gender = action  # "male" or "female"

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        await user_repo.update_nutrition_settings(callback.from_user.id, gender=gender)
        await session.commit()

    await state.clear()
    gender_text = "👨 Чоловік" if gender == "male" else "👩 Жінка"
    await callback.answer(f"✅ Стать оновлено: {gender_text}")

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        nutrition = await user_repo.get_nutrition_settings(callback.from_user.id)
        if nutrition is None:
            return
        text = _format_nutrition_settings(nutrition)
        keyboard = get_nutrition_settings_keyboard(nutrition["water_tracking_enabled"])
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "edit:water")
async def start_edit_water(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing daily water goal."""
    if not isinstance(callback.message, Message):
        return

    await state.set_state(ProfileSettingsStates.edit_water)
    await callback.message.edit_text(
        "💧 *Введіть денну норму води в мл (від 500 до 10000):*",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(ProfileSettingsStates.edit_water)
async def process_edit_water(message: Message, state: FSMContext) -> None:
    """Process water goal input."""
    if message.from_user is None or message.text is None:
        return

    try:
        water = int(message.text.strip())
        if not 500 <= water <= 10000:
            raise ValueError("Water out of range")
    except ValueError:
        await message.answer("❌ Введіть число від 500 до 10000")
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        await user_repo.update_nutrition_settings(message.from_user.id, daily_water_ml=water)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Денну норму води оновлено: {water} мл")

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        nutrition = await user_repo.get_nutrition_settings(message.from_user.id)
        if nutrition is None:
            return
        text = _format_nutrition_settings(nutrition)
        keyboard = get_nutrition_settings_keyboard(nutrition["water_tracking_enabled"])
        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "edit:water_toggle")
async def enable_water_tracking(callback: CallbackQuery) -> None:
    """Turn water tracking back on (GYM-25).

    Shown instead of ``edit:water`` while tracking is off — a tap
    re-enables it and redisplays the settings screen, where the button is
    now the normal "💧 Денна норма води" one to actually edit the goal.
    """
    if not isinstance(callback.message, Message):
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        await user_repo.update_nutrition_settings(
            callback.from_user.id, water_tracking_enabled=True
        )
        await session.commit()

        nutrition = await user_repo.get_nutrition_settings(callback.from_user.id)
        if nutrition is None:
            await callback.message.edit_text("❌ Профіль не знайдено")
            await callback.answer()
            return

        text = _format_nutrition_settings(nutrition)
        keyboard = get_nutrition_settings_keyboard(nutrition["water_tracking_enabled"])
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
        await callback.answer("💧 Відстеження води увімкнено")


@router.callback_query(F.data == "edit:calories")
async def start_edit_calories(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing daily calories goal."""
    if not isinstance(callback.message, Message):
        return

    await state.set_state(ProfileSettingsStates.edit_calories)
    await callback.message.edit_text(
        "🔥 *Введіть денну норму калорій (від 1000 до 10000):*",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(ProfileSettingsStates.edit_calories)
async def process_edit_calories(message: Message, state: FSMContext) -> None:
    """Process calories goal input."""
    if message.from_user is None or message.text is None:
        return

    try:
        calories = int(message.text.strip())
        if not 1000 <= calories <= 10000:
            raise ValueError("Calories out of range")
    except ValueError:
        await message.answer("❌ Введіть число від 1000 до 10000")
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        await user_repo.update_nutrition_settings(message.from_user.id, daily_calories=calories)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Денну норму калорій оновлено: {calories} ккал")

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        nutrition = await user_repo.get_nutrition_settings(message.from_user.id)
        if nutrition is None:
            return
        text = _format_nutrition_settings(nutrition)
        keyboard = get_nutrition_settings_keyboard(nutrition["water_tracking_enabled"])
        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "edit:protein")
async def start_edit_protein(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing daily protein goal."""
    if not isinstance(callback.message, Message):
        return

    await state.set_state(ProfileSettingsStates.edit_protein)
    await callback.message.edit_text(
        "🥩 *Введіть денну норму білків в грамах (від 10 до 500):*",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(ProfileSettingsStates.edit_protein)
async def process_edit_protein(message: Message, state: FSMContext) -> None:
    """Process protein goal input."""
    if message.from_user is None or message.text is None:
        return

    try:
        protein = int(message.text.strip())
        if not 10 <= protein <= 500:
            raise ValueError("Protein out of range")
    except ValueError:
        await message.answer("❌ Введіть число від 10 до 500")
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        await user_repo.update_nutrition_settings(message.from_user.id, daily_protein=protein)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Денну норму білків оновлено: {protein} г")

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        nutrition = await user_repo.get_nutrition_settings(message.from_user.id)
        if nutrition is None:
            return
        text = _format_nutrition_settings(nutrition)
        keyboard = get_nutrition_settings_keyboard(nutrition["water_tracking_enabled"])
        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "edit:fats")
async def start_edit_fats(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing daily fats goal."""
    if not isinstance(callback.message, Message):
        return

    await state.set_state(ProfileSettingsStates.edit_fats)
    await callback.message.edit_text(
        "🧈 *Введіть денну норму жирів в грамах (від 10 до 300):*",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(ProfileSettingsStates.edit_fats)
async def process_edit_fats(message: Message, state: FSMContext) -> None:
    """Process fats goal input."""
    if message.from_user is None or message.text is None:
        return

    try:
        fats = int(message.text.strip())
        if not 10 <= fats <= 300:
            raise ValueError("Fats out of range")
    except ValueError:
        await message.answer("❌ Введіть число від 10 до 300")
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        await user_repo.update_nutrition_settings(message.from_user.id, daily_fats=fats)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Денну норму жирів оновлено: {fats} г")

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        nutrition = await user_repo.get_nutrition_settings(message.from_user.id)
        if nutrition is None:
            return
        text = _format_nutrition_settings(nutrition)
        keyboard = get_nutrition_settings_keyboard(nutrition["water_tracking_enabled"])
        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "edit:carbs")
async def start_edit_carbs(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing daily carbs goal."""
    if not isinstance(callback.message, Message):
        return

    await state.set_state(ProfileSettingsStates.edit_carbs)
    await callback.message.edit_text(
        "🍞 *Введіть денну норму вуглеводів в грамах (від 10 до 700):*",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.message(ProfileSettingsStates.edit_carbs)
async def process_edit_carbs(message: Message, state: FSMContext) -> None:
    """Process carbs goal input."""
    if message.from_user is None or message.text is None:
        return

    try:
        carbs = int(message.text.strip())
        if not 10 <= carbs <= 700:
            raise ValueError("Carbs out of range")
    except ValueError:
        await message.answer("❌ Введіть число від 10 до 700")
        return

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        await user_repo.update_nutrition_settings(message.from_user.id, daily_carbs=carbs)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Денну норму вуглеводів оновлено: {carbs} г")

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        nutrition = await user_repo.get_nutrition_settings(message.from_user.id)
        if nutrition is None:
            return
        text = _format_nutrition_settings(nutrition)
        keyboard = get_nutrition_settings_keyboard(nutrition["water_tracking_enabled"])
        await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
