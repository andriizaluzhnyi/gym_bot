"""Workout program handlers for creating training programs."""

import logging
from datetime import datetime
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from urllib.parse import quote

from src.bot.keyboards import (
    get_add_more_exercise_keyboard,
    get_admin_menu_keyboard,
    get_day_selection_keyboard,
    get_main_menu_keyboard,
    get_muscle_group_keyboard,
    get_reps_keyboard,
    get_sets_keyboard,
    get_start_workout_keyboard,
    get_user_selection_keyboard,
    get_view_day_filter_keyboard,
    get_view_muscle_filter_keyboard,
)
from src.config import get_settings
from src.database.models import User
from src.database.repository import UserRepository, WorkoutProgramRepository
from src.database.session import async_session_maker
from src.services.google_sheets import GoogleSheetsService
from src.services.workout_program_parsing import (
    combine_sets_reps,
    looks_like_combined_sets_reps,
)

router = Router()
settings = get_settings()
logger = logging.getLogger(__name__)


async def _get_workout_users() -> list[str]:
    """Get list of usernames from database."""
    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        users = await user_repo.get_all_with_username()
        return [user.username for user in users if user.username]


async def _resolve_owner(
    session: AsyncSession, telegram_id: int, selected_user: str | None
) -> User | None:
    """Resolve the DB owner of the program being built/viewed in this FSM
    session (GYM-28).

    ``selected_user`` is a username chosen from the picker — reachable
    only by an admin (see ``is_admin`` guard below); ``None`` means "the
    caller's own account", either because they're not an admin (no picker
    was ever shown) or because no other users existed yet to pick from.
    """
    user_repo = UserRepository(session)
    if selected_user:
        return await user_repo.get_by_username(selected_user)
    return await user_repo.get_by_telegram_id(telegram_id)


class WorkoutProgramStates(StatesGroup):
    """States for creating workout program."""

    select_user = State()
    select_day = State()
    muscle_group = State()
    exercise_name = State()
    sets = State()
    reps = State()
    comment = State()
    add_more = State()
    # Viewing states
    view_filter_muscle = State()
    view_filter_day = State()


def is_admin(user_id: int) -> bool:
    """Check if user is admin.

    GYM-28: real check (was stubbed to always return True) — a non-admin
    now only ever builds/views their own program, never a picker of every
    username in the DB.
    """
    return user_id in settings.admin_user_ids


@router.message(F.text == "💪 Програма тренувань")
async def start_workout_program(message: Message, state: FSMContext) -> None:
    """Start creating a workout program.

    GYM-28: a non-admin never sees the user picker at all — they always
    build their own program, the same branch as "no other users exist yet
    to pick from" below.
    """
    if message.from_user is None:
        return

    workout_users = (
        await _get_workout_users() if is_admin(message.from_user.id) else []
    )

    if workout_users:
        # Ask to select user first
        await state.set_state(WorkoutProgramStates.select_user)
        await state.update_data(exercises=[])

        keyboard = get_user_selection_keyboard(workout_users)
        await message.answer(
            "💪 *Програма тренувань*\n\n"
            "Оберіть користувача:",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    else:
        # No users in database, proceed directly
        await state.set_state(WorkoutProgramStates.muscle_group)
        await state.update_data(exercises=[], selected_user=None)

        keyboard = get_muscle_group_keyboard()
        await message.answer(
            "💪 *Програма тренувань*\n\n"
            "Оберіть групу м'язів:",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )


@router.callback_query(F.data.startswith("user:"))
async def process_user_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """Process user selection."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    action = callback.data.split(":")[1]

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Операцію скасовано")
        await callback.answer()
        return

    user_name = action
    data = await state.get_data()

    # Check if we're in viewing mode
    if data.get("viewing_mode"):
        await state.update_data(selected_user=user_name)
        await state.set_state(WorkoutProgramStates.view_filter_muscle)

        keyboard = get_view_muscle_filter_keyboard()
        await callback.message.edit_text(
            f"📋 *Програми для {user_name}*\n\n"
            "Оберіть групу м'язів для фільтрації:",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        await callback.answer()
        return

    # Creating mode - proceed to muscle group selection
    await state.update_data(selected_user=user_name)
    await state.set_state(WorkoutProgramStates.muscle_group)

    keyboard = get_muscle_group_keyboard()
    await callback.message.edit_text(
        f"💪 *Програма тренувань для {user_name}*\n\n"
        "Оберіть групу м'язів:",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("day:"))
async def process_day_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """Process day selection."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    parts = callback.data.split(":")
    action = parts[1]

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Створення програми скасовано")
        await callback.answer()
        return

    day_num = int(parts[2])
    await state.update_data(day_number=day_num, is_new_day=(action == "new"))
    await state.set_state(WorkoutProgramStates.exercise_name)

    data = await state.get_data()
    muscle_group = data.get("current_muscle_group", "")
    selected_user = data.get("selected_user")
    user_prefix = f"👤 {selected_user} | " if selected_user else ""

    await callback.message.edit_text(
        f"{user_prefix}📅 *День {day_num}* | {muscle_group}\n\n"
        "Введіть назву вправи:",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("muscle:"))
async def process_muscle_group(callback: CallbackQuery, state: FSMContext) -> None:
    """Process muscle group selection."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    action = callback.data.split(":")[1]

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Створення програми скасовано")
        await callback.answer()
        return

    muscle_group = action
    await state.update_data(current_muscle_group=muscle_group)

    # Check if day is already selected in this session
    data = await state.get_data()
    current_day = data.get("day_number")
    selected_user = data.get("selected_user")

    if current_day:
        # Day already selected, proceed to exercise name
        await state.set_state(WorkoutProgramStates.exercise_name)
        user_prefix = f"👤 {selected_user} | " if selected_user else ""
        await callback.message.edit_text(
            f"{user_prefix}📅 *День {current_day}* | {muscle_group}\n\n"
            "Введіть назву вправи:",
            parse_mode="Markdown",
        )
    else:
        # First exercise, need to select day
        await state.set_state(WorkoutProgramStates.select_day)

        # Get last day for this muscle group from the DB (GYM-28)
        last_day = 0
        async with async_session_maker() as session:
            owner = await _resolve_owner(session, callback.from_user.id, selected_user)
            if owner:
                last_day = await WorkoutProgramRepository(
                    session
                ).get_last_day_for_muscle(owner.id, muscle_group)

        keyboard = get_day_selection_keyboard(last_day)
        user_prefix = f"👤 {selected_user} | " if selected_user else ""
        await callback.message.edit_text(
            f"{user_prefix}💪 *{muscle_group}*\n\n"
            "Оберіть день для програми:",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    await callback.answer()


@router.message(WorkoutProgramStates.exercise_name)
async def process_exercise_name(message: Message, state: FSMContext) -> None:
    """Process exercise name input."""
    if message.text is None:
        return

    exercise_name = message.text.strip()
    await state.update_data(current_exercise=exercise_name)
    await state.set_state(WorkoutProgramStates.sets)

    data = await state.get_data()
    day_num = data.get("day_number", 1)
    muscle = data.get("current_muscle_group", "")

    keyboard = get_sets_keyboard()
    await message.answer(
        f"📅 *День {day_num}* | {muscle}\n"
        f"💪 Вправа: *{exercise_name}*\n\n"
        "Оберіть кількість підходів або введіть вручну:",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("sets:"))
async def process_sets_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Process sets selection from keyboard."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    action = callback.data.split(":")[1]

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Створення програми скасовано")
        await callback.answer()
        return

    sets = action
    await state.update_data(current_sets=sets)
    await state.set_state(WorkoutProgramStates.reps)

    data = await state.get_data()
    day_num = data.get("day_number", 1)

    keyboard = get_reps_keyboard()
    await callback.message.edit_text(
        f"📅 *День {day_num}*\n"
        f"✅ Підходів: *{sets}*\n\n"
        "Оберіть кількість повторень або введіть вручну:",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(WorkoutProgramStates.sets)
async def process_sets_text(message: Message, state: FSMContext) -> None:
    """Process manual sets input."""
    if message.text is None:
        return

    sets = message.text.strip()

    data = await state.get_data()
    day_num = data.get("day_number", 1)

    # Check if it's a combined format (contains / or |) — shared with
    # POST /api/workout/program/exercise (GYM-30), see
    # src/services/workout_program_parsing.py.
    if looks_like_combined_sets_reps(sets):
        # Combined format - skip reps step
        await state.update_data(current_sets=sets, current_reps="")
        await state.set_state(WorkoutProgramStates.comment)

        await message.answer(
            f"📅 *День {day_num}*\n"
            f"✅ Підходи/Повторення: *{sets}*\n\n"
            "Додайте коментар до вправи\n"
            "(або надішліть '-' щоб пропустити):",
            parse_mode="Markdown",
        )
    else:
        # Regular sets input - continue to reps
        await state.update_data(current_sets=sets)
        await state.set_state(WorkoutProgramStates.reps)

        keyboard = get_reps_keyboard()
        await message.answer(
            f"📅 *День {day_num}*\n"
            f"✅ Підходів: *{sets}*\n\n"
            "Оберіть кількість повторень або введіть вручну:",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )


@router.callback_query(F.data.startswith("reps:"))
async def process_reps_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Process reps selection from keyboard."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    action = callback.data.split(":")[1]

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Створення програми скасовано")
        await callback.answer()
        return

    reps = action
    await state.update_data(current_reps=reps)
    await state.set_state(WorkoutProgramStates.comment)

    data = await state.get_data()
    day_num = data.get("day_number", 1)

    await callback.message.edit_text(
        f"📅 *День {day_num}*\n"
        f"✅ Повторень: *{reps}*\n\n"
        "Додайте коментар до вправи\n"
        "(або надішліть '-' щоб пропустити):",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(WorkoutProgramStates.reps)
async def process_reps_text(message: Message, state: FSMContext) -> None:
    """Process manual reps input."""
    if message.text is None:
        return

    reps = message.text.strip()
    await state.update_data(current_reps=reps)
    await state.set_state(WorkoutProgramStates.comment)

    data = await state.get_data()
    day_num = data.get("day_number", 1)

    await message.answer(
        f"📅 *День {day_num}*\n"
        f"✅ Повторень: *{reps}*\n\n"
        "Додайте коментар до вправи\n"
        "(або надішліть '-' щоб пропустити):",
        parse_mode="Markdown",
    )


@router.message(WorkoutProgramStates.comment)
async def process_comment(message: Message, state: FSMContext) -> None:
    """Process comment input and save exercise."""
    if message.text is None:
        return

    comment = message.text.strip() if message.text.strip() != "-" else ""

    data = await state.get_data()
    sets = data.get("current_sets", "")
    reps = data.get("current_reps", "")

    # If reps is empty, sets contains combined format already — shared
    # with POST /api/workout/program/exercise (GYM-30), see
    # src/services/workout_program_parsing.py.
    sets_reps = combine_sets_reps(sets, reps)

    # Create exercise record with combined sets_reps field
    exercise = {
        "day": data.get("day_number", 1),
        "muscle_group": data["current_muscle_group"],
        "exercise": data["current_exercise"],
        "sets_reps": sets_reps,
        "comment": comment,
        "created_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }

    # Add to exercises list
    exercises = data.get("exercises", [])
    exercises.append(exercise)
    await state.update_data(exercises=exercises)

    await state.set_state(WorkoutProgramStates.add_more)

    # Show summary
    day_num = data.get("day_number", 1)
    summary = f"✅ *Вправа додана до Дня {day_num}!*\n\n"
    summary += f"🦴 Група: {exercise['muscle_group']}\n"
    summary += f"💪 Вправа: {exercise['exercise']}\n"
    summary += f"📊 Підходи/Повторення: {sets_reps}\n"
    if comment:
        summary += f"💬 Коментар: {comment}\n"

    summary += f"\n📝 Всього вправ сьогодні: {len(exercises)}"

    keyboard = get_add_more_exercise_keyboard()
    await message.answer(summary, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data.startswith("program:"))
async def process_program_action(callback: CallbackQuery, state: FSMContext) -> None:
    """Process program actions (add more or finish)."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    action = callback.data.split(":")[1]

    if action == "add_more":
        await state.set_state(WorkoutProgramStates.exercise_name)
        data = await state.get_data()
        day_num = data.get("day_number", 1)
        muscle_group = data.get("current_muscle_group", "")
        selected_user = data.get("selected_user")
        user_prefix = f"👤 {selected_user} | " if selected_user else ""

        await callback.message.edit_text(
            f"{user_prefix}📅 *День {day_num}* | {muscle_group}\n\n"
            "Введіть назву вправи:",
            parse_mode="Markdown",
        )
        await callback.answer()
        return

    if action == "finish":
        # Answer callback immediately to prevent timeout
        await callback.answer("⏳ Зберігаємо...")

        data = await state.get_data()
        exercises = data.get("exercises", [])
        day_num = data.get("day_number", 1)
        selected_user = data.get("selected_user")

        if not exercises:
            await callback.message.edit_text("❌ Програма порожня!")
            await state.clear()
            return

        # DB is the primary store (GYM-28) — Sheets is an opt-in mirror,
        # same convention as workout logs (GYM-2): it's written to only if
        # the owner enabled sync_workout_to_sheets, and a Sheets failure
        # never affects whether the program was actually saved.
        async with async_session_maker() as session:
            owner = await _resolve_owner(session, callback.from_user.id, selected_user)
            if not owner:
                await callback.message.edit_text("❌ Користувача не знайдено")
                await state.clear()
                return

            await WorkoutProgramRepository(session).add_exercises(
                owner.id, day_num, exercises
            )
            await session.commit()

            sync_enabled = owner.sync_workout_to_sheets
            owner_username = owner.username

        sheets_saved = False
        if sync_enabled and owner_username:
            try:
                sheets_service = GoogleSheetsService()
                sheets_saved = await sheets_service.add_workout_program(
                    exercises, user_name=owner_username
                )
            except Exception as e:
                logger.warning(f"Failed to mirror workout program to Sheets: {e}")
                sheets_saved = False

        # Show final summary
        user_header = f" для {selected_user}" if selected_user else ""
        summary = f"✅ *День {day_num}{user_header} збережено!*\n\n"

        # Group by muscle group
        by_group: dict[str, list[dict[str, Any]]] = {}
        for ex in exercises:
            group = ex["muscle_group"]
            if group not in by_group:
                by_group[group] = []
            by_group[group].append(ex)

        for group, exs in by_group.items():
            summary += f"\n*{group}:*\n"
            for ex in exs:
                summary += f"  • {ex['exercise']} - {ex['sets_reps']}"
                if ex.get("comment"):
                    summary += f" ({ex['comment']})"
                summary += "\n"

        if sync_enabled:
            if sheets_saved:
                summary += "\n📊 Продубльовано в Google Sheets"
            else:
                summary += "\n⚠️ Не вдалося продублювати в Google Sheets"

        await callback.message.edit_text(summary, parse_mode="Markdown")
        await callback.message.answer(
            "Оберіть наступну дію:",
            reply_markup=(
                get_admin_menu_keyboard()
                if is_admin(callback.from_user.id)
                else get_main_menu_keyboard()
            ),
        )

        await state.clear()


@router.message(F.text == "📋 Переглянути програми")
async def view_programs(message: Message, state: FSMContext) -> None:
    """View saved workout programs - select user first if users exist.

    GYM-28: a non-admin never sees the user picker — they always view
    only their own program, same branch as "no other users exist yet"
    below.
    """
    if message.from_user is None:
        return

    workout_users = (
        await _get_workout_users() if is_admin(message.from_user.id) else []
    )

    if workout_users:
        # Ask to select user first
        keyboard = get_user_selection_keyboard(workout_users)
        await state.set_state(WorkoutProgramStates.select_user)
        await state.update_data(viewing_mode=True)
        await message.answer(
            "📋 *Перегляд програм*\n\n"
            "Оберіть користувача:",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    else:
        # No users in database, go directly to muscle filter
        await state.set_state(WorkoutProgramStates.view_filter_muscle)
        await state.update_data(viewing_mode=True, selected_user=None)

        keyboard = get_view_muscle_filter_keyboard()
        await message.answer(
            "📋 *Перегляд програм*\n\n"
            "Оберіть групу м'язів для фільтрації:",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )


@router.callback_query(F.data.startswith("view_muscle:"))
async def process_view_muscle_filter(callback: CallbackQuery, state: FSMContext) -> None:
    """Process muscle group filter selection for viewing."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    action = callback.data.split(":")[1]

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Операцію скасовано")
        await callback.answer()
        return

    data = await state.get_data()
    selected_user = data.get("selected_user")

    if action == "all":
        await state.update_data(filter_muscle_group=None)
    else:
        await state.update_data(filter_muscle_group=action)

    # Get available days for this user and muscle group (GYM-28: DB)
    try:
        async with async_session_maker() as session:
            owner = await _resolve_owner(session, callback.from_user.id, selected_user)
            if not owner:
                await callback.message.edit_text("❌ Користувача не знайдено")
                await callback.answer()
                return

            summary = await WorkoutProgramRepository(session).get_days_summary(owner.id)

        # Filter by muscle group if selected
        days = {
            row["day"] for row in summary
            if action == "all" or action in row["muscle_groups"]
        }

        if not days:
            # No days found, show programs directly
            filter_muscle = None if action == "all" else action
            await state.clear()
            await callback.message.edit_text(
                "📋 *Завантаження програм...*",
                parse_mode="Markdown"
            )
            await _show_programs_filtered(
                callback.message,
                callback.from_user.id,
                user_name=selected_user,
                muscle_group=filter_muscle,
                day=None
            )
            await callback.answer()
            return

        await state.set_state(WorkoutProgramStates.view_filter_day)
        keyboard = get_view_day_filter_keyboard(list(days))

        filter_text = f" ({action})" if action != "all" else ""
        await callback.message.edit_text(
            f"📋 *Програми для {selected_user}{filter_text}*\n\n"
            "Оберіть день для фільтрації:",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    except Exception as e:
        await callback.message.edit_text(f"❌ Помилка: {str(e)}")

    await callback.answer()


@router.callback_query(F.data.startswith("view_day:"))
async def process_view_day_filter(callback: CallbackQuery, state: FSMContext) -> None:
    """Process day filter selection for viewing."""
    if not callback.data or not isinstance(callback.message, Message):
        return

    action = callback.data.split(":")[1]

    if action == "back":
        # Go back to muscle group selection
        data = await state.get_data()
        selected_user = data.get("selected_user")
        await state.set_state(WorkoutProgramStates.view_filter_muscle)

        keyboard = get_view_muscle_filter_keyboard()
        await callback.message.edit_text(
            f"📋 *Програми для {selected_user}*\n\n"
            "Оберіть групу м'язів для фільтрації:",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        await callback.answer()
        return

    data = await state.get_data()
    selected_user = data.get("selected_user")
    filter_muscle = data.get("filter_muscle_group")

    if action == "all":
        filter_day = None
    else:
        filter_day = int(action)

    await state.clear()
    await callback.message.edit_text(
        "📋 *Завантаження програм...*",
        parse_mode="Markdown"
    )
    await _show_programs_filtered(
        callback.message,
        callback.from_user.id,
        user_name=selected_user,
        muscle_group=filter_muscle,
        day=filter_day
    )
    await callback.answer()


async def _show_programs_filtered(
    message: Message,
    caller_telegram_id: int,
    user_name: str | None = None,
    muscle_group: str | None = None,
    day: int | None = None
) -> None:
    """Show programs filtered by muscle group and/or day (GYM-28: DB).

    After displaying the program, shows a 'Start Workout' WebApp button
    when a specific day is selected.

    Args:
        message: Message to reply to. Note this is often `callback.message`
            (the bot's own message being edited), whose `from_user` is the
            *bot*, not the person who tapped the button — so the caller's
            identity has to be passed in separately rather than read off
            `message.from_user` here.
        caller_telegram_id: telegram_id of whoever triggered this (for
            resolving the "no specific user picked" case to their own
            account, GYM-28).
        user_name: User name to filter by
        muscle_group: Muscle group to filter by (None for all)
        day: Day number to filter by (None for all)
    """
    try:
        async with async_session_maker() as session:
            owner = await _resolve_owner(session, caller_telegram_id, user_name)
            if not owner:
                await message.answer("❌ Користувача не знайдено")
                return
            programs = await WorkoutProgramRepository(session).get_program(
                owner.id, day=day, muscle=muscle_group
            )

        # Build header
        user_header = f" ({user_name})" if user_name else ""
        filter_parts = []
        if muscle_group:
            filter_parts.append(muscle_group)
        if day is not None:
            filter_parts.append(f"День {day}")
        filter_header = f" | {' | '.join(filter_parts)}" if filter_parts else ""

        if not programs:
            await message.answer(
                f"📋 *Програма тренувань{user_header}{filter_header}*\n\n"
                "_Немає записів за вибраними критеріями_",
                parse_mode="Markdown",
            )
            return

        # Group by day
        by_day: dict[Any, list[dict[str, Any]]] = {}
        for p in programs:
            d = p.get("day", "?")
            if d not in by_day:
                by_day[d] = []
            by_day[d].append(p)

        text = f"📋 *Програма тренувань{user_header}{filter_header}*\n"
        text += "━" * 20 + "\n"

        for d in sorted(by_day.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
            text += f"\n📅 *День {d}*\n"

            # Group by muscle in this day
            by_muscle: dict[Any, list[dict[str, Any]]] = {}
            for ex in by_day[d]:
                m = ex.get("muscle_group", "Інше")
                if m not in by_muscle:
                    by_muscle[m] = []
                by_muscle[m].append(ex)

            for m, exercises in by_muscle.items():
                text += f"\n  *{m}*\n"
                for ex in exercises:
                    line = f"    • {ex.get('exercise', '-')}"
                    sets_reps = ex.get("sets_reps", "")
                    if sets_reps:
                        line += f" ({sets_reps})"
                    comment = ex.get("comment", "")
                    if comment:
                        line += f" - _{comment}_"
                    text += line + "\n"

            text += "\n" + "─" * 15 + "\n"

        # Split if too long
        if len(text) > 4000:
            text = text[:3900] + "\n\n_...і ще записи_"

        await message.answer(text, parse_mode="Markdown")

        # Show "Start Workout" WebApp button when a specific day is
        # selected. Uses owner.username (resolved above) rather than the
        # raw user_name param, so this also works for a non-admin's own
        # self-view (user_name is None there — GYM-28).
        webapp_url = settings.webapp_url
        if webapp_url and owner.username and day is not None:
            muscle_param = quote(muscle_group) if muscle_group else ''
            workout_url = (
                f'{webapp_url}/workout'
                f'?user={quote(owner.username)}'
                f'&day={day}'
                f'&muscle={muscle_param}'
            )
            keyboard = get_start_workout_keyboard(workout_url)
            await message.answer(
                '👇 Готові тренуватися?',
                reply_markup=keyboard,
            )

    except Exception as e:
        await message.answer(
            f"❌ Помилка при завантаженні програм: {str(e)}",
        )
