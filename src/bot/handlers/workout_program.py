"""Workout program handlers for creating training programs."""

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards import (
    get_add_more_exercise_keyboard,
    get_admin_menu_keyboard,
    get_day_selection_keyboard,
    get_muscle_group_keyboard,
    get_sets_reps_keyboard,
)
from src.config import get_settings
from src.services.google_sheets import GoogleSheetsService

router = Router()
settings = get_settings()


class WorkoutProgramStates(StatesGroup):
    """States for creating workout program."""

    select_day = State()
    muscle_group = State()
    exercise_name = State()
    sets_reps = State()
    comment = State()
    add_more = State()


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return user_id in settings.admin_user_ids


@router.message(F.text == "💪 Програма тренувань")
async def start_workout_program(message: Message, state: FSMContext) -> None:
    """Start creating a workout program."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас немає прав для цієї дії")
        return

    await state.set_state(WorkoutProgramStates.muscle_group)
    await state.update_data(exercises=[])

    keyboard = get_muscle_group_keyboard()
    await message.answer(
        "💪 *Програма тренувань*\n\n"
        "Оберіть групу м'язів:",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("day:"))
async def process_day_selection(callback: CallbackQuery, state: FSMContext) -> None:
    """Process day selection."""
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

    await callback.message.edit_text(
        f"📅 *День {day_num}* | {muscle_group}\n\n"
        "Введіть назву вправи:",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("muscle:"))
async def process_muscle_group(callback: CallbackQuery, state: FSMContext) -> None:
    """Process muscle group selection."""
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

    if current_day:
        # Day already selected, proceed to exercise name
        await state.set_state(WorkoutProgramStates.exercise_name)
        await callback.message.edit_text(
            f"📅 *День {current_day}* | {muscle_group}\n\n"
            "Введіть назву вправи:",
            parse_mode="Markdown",
        )
    else:
        # First exercise, need to select day
        await state.set_state(WorkoutProgramStates.select_day)

        # Get last day for this muscle group from sheets
        try:
            sheets_service = GoogleSheetsService()
            last_day = await sheets_service.get_last_program_day_for_muscle_group(
                muscle_group
            )
        except Exception:
            last_day = 0

        keyboard = get_day_selection_keyboard(last_day)
        await callback.message.edit_text(
            f"💪 *{muscle_group}*\n\n"
            "Оберіть день для програми:",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    await callback.answer()


@router.message(WorkoutProgramStates.exercise_name)
async def process_exercise_name(message: Message, state: FSMContext) -> None:
    """Process exercise name input."""
    exercise_name = message.text.strip()
    await state.update_data(current_exercise=exercise_name)
    await state.set_state(WorkoutProgramStates.sets_reps)

    data = await state.get_data()
    day_num = data.get("day_number", 1)
    muscle = data.get("current_muscle_group", "")

    keyboard = get_sets_reps_keyboard()
    await message.answer(
        f"📅 *День {day_num}* | {muscle}\n"
        f"💪 Вправа: *{exercise_name}*\n\n"
        "Оберіть або введіть підходи/повторення:\n"
        "_Приклади: 4/12, 3/15, 2/15 | 3/10, 10-12/4_",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("setsreps:"))
async def process_sets_reps_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Process sets/reps selection from keyboard."""
    action = callback.data.split(":")[1]

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Створення програми скасовано")
        await callback.answer()
        return

    sets_reps = action
    await state.update_data(current_sets_reps=sets_reps)
    await state.set_state(WorkoutProgramStates.comment)

    data = await state.get_data()
    day_num = data.get("day_number", 1)

    await callback.message.edit_text(
        f"📅 *День {day_num}*\n"
        f"✅ Підходи/Повторення: *{sets_reps}*\n\n"
        "Додайте коментар до вправи\n"
        "(або надішліть '-' щоб пропустити):",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(WorkoutProgramStates.sets_reps)
async def process_sets_reps_text(message: Message, state: FSMContext) -> None:
    """Process manual sets/reps input."""
    sets_reps = message.text.strip()
    await state.update_data(current_sets_reps=sets_reps)
    await state.set_state(WorkoutProgramStates.comment)

    data = await state.get_data()
    day_num = data.get("day_number", 1)

    await message.answer(
        f"📅 *День {day_num}*\n"
        f"✅ Підходи/Повторення: *{sets_reps}*\n\n"
        "Додайте коментар до вправи\n"
        "(або надішліть '-' щоб пропустити):",
        parse_mode="Markdown",
    )


@router.message(WorkoutProgramStates.comment)
async def process_comment(message: Message, state: FSMContext) -> None:
    """Process comment input and save exercise."""
    comment = message.text.strip() if message.text.strip() != "-" else ""

    data = await state.get_data()
    sets_reps = data.get("current_sets_reps", "")

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
    action = callback.data.split(":")[1]

    if action == "add_more":
        await state.set_state(WorkoutProgramStates.exercise_name)
        data = await state.get_data()
        day_num = data.get("day_number", 1)
        muscle_group = data.get("current_muscle_group", "")

        await callback.message.edit_text(
            f"📅 *День {day_num}* | {muscle_group}\n\n"
            "Введіть назву вправи:",
            parse_mode="Markdown",
        )
        await callback.answer()
        return

    if action == "finish":
        data = await state.get_data()
        exercises = data.get("exercises", [])
        day_num = data.get("day_number", 1)

        if not exercises:
            await callback.message.edit_text("❌ Програма порожня!")
            await state.clear()
            await callback.answer()
            return

        # Save to Google Sheets
        try:
            sheets_service = GoogleSheetsService()
            await sheets_service.add_workout_program(exercises)
            sheets_saved = True
        except Exception as e:
            print(f"Error saving to sheets: {e}")
            sheets_saved = False

        # Show final summary
        summary = f"✅ *День {day_num} збережено!*\n\n"

        # Group by muscle group
        by_group = {}
        for ex in exercises:
            group = ex["muscle_group"]
            if group not in by_group:
                by_group[group] = []
            by_group[group].append(ex)

        for group, exs in by_group.items():
            summary += f"\n*{group}:*\n"
            for ex in exs:
                summary += f"  • {ex['exercise']} - {ex['sets']}×{ex['reps']}"
                if ex.get("comment"):
                    summary += f" ({ex['comment']})"
                summary += "\n"

        if sheets_saved:
            summary += "\n📊 Збережено в Google Sheets"
        else:
            summary += "\n⚠️ Не вдалося зберегти в Google Sheets"

        await callback.message.edit_text(summary, parse_mode="Markdown")
        await callback.message.answer(
            "Оберіть наступну дію:",
            reply_markup=get_admin_menu_keyboard(),
        )

        await state.clear()
        await callback.answer("✅ Програма збережена!")


@router.message(F.text == "📋 Переглянути програми")
async def view_programs(message: Message) -> None:
    """View saved workout programs grouped by days."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас немає прав для цієї дії")
        return

    try:
        sheets_service = GoogleSheetsService()
        programs = await sheets_service.get_workout_programs(limit=100)

        if not programs:
            await message.answer(
                "📋 *Програма тренувань*\n\n"
                "_Поки немає збережених програм_",
                parse_mode="Markdown",
            )
            return

        # Group by day
        by_day = {}
        for p in programs:
            day = p.get("day", "?")
            if day not in by_day:
                by_day[day] = []
            by_day[day].append(p)

        text = "📋 *Програма тренувань*\n"
        text += "━" * 20 + "\n"

        for day in sorted(by_day.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
            text += f"\n📅 *День {day}*\n"

            # Group by muscle in this day
            by_muscle = {}
            for ex in by_day[day]:
                muscle = ex.get("muscle_group", "Інше")
                if muscle not in by_muscle:
                    by_muscle[muscle] = []
                by_muscle[muscle].append(ex)

            for muscle, exercises in by_muscle.items():
                text += f"\n  *{muscle}*\n"
                for ex in exercises:
                    line = f"    • {ex.get('exercise', '-')}"
                    sets = ex.get("sets", "")
                    reps = ex.get("reps", "")
                    if sets and reps:
                        line += f" ({sets}×{reps})"
                    comment = ex.get("comment", "")
                    if comment:
                        line += f" - _{comment}_"
                    text += line + "\n"

            text += "\n" + "─" * 15 + "\n"

        # Split if too long
        if len(text) > 4000:
            text = text[:3900] + "\n\n_...і ще записи_"

        await message.answer(text, parse_mode="Markdown")

    except Exception as e:
        await message.answer(
            f"❌ Помилка при завантаженні програм: {str(e)}",
        )
