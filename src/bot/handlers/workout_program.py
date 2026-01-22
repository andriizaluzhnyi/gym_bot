"""Workout program handlers for creating training programs."""

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from src.bot.keyboards import (
    get_add_more_exercise_keyboard,
    get_admin_menu_keyboard,
    get_muscle_group_keyboard,
    get_reps_keyboard,
    get_sets_keyboard,
)
from src.config import get_settings
from src.services.google_sheets import GoogleSheetsService

router = Router()
settings = get_settings()


class WorkoutProgramStates(StatesGroup):
    """States for creating workout program."""

    muscle_group = State()
    exercise_name = State()
    sets = State()
    reps = State()
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
        "💪 *Створення програми тренувань*\n\n"
        "Оберіть групу м'язів:",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


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
    await state.set_state(WorkoutProgramStates.exercise_name)

    await callback.message.edit_text(
        f"✅ Група м'язів: *{muscle_group}*\n\n"
        "Введіть назву вправи:",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(WorkoutProgramStates.exercise_name)
async def process_exercise_name(message: Message, state: FSMContext) -> None:
    """Process exercise name input."""
    exercise_name = message.text.strip()
    await state.update_data(current_exercise=exercise_name)
    await state.set_state(WorkoutProgramStates.sets)

    keyboard = get_sets_keyboard()
    await message.answer(
        f"✅ Вправа: *{exercise_name}*\n\n"
        "Оберіть кількість підходів:",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("sets:"))
async def process_sets(callback: CallbackQuery, state: FSMContext) -> None:
    """Process sets selection."""
    action = callback.data.split(":")[1]

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Створення програми скасовано")
        await callback.answer()
        return

    sets = int(action)
    await state.update_data(current_sets=sets)
    await state.set_state(WorkoutProgramStates.reps)

    keyboard = get_reps_keyboard()
    await callback.message.edit_text(
        f"✅ Підходів: *{sets}*\n\n"
        "Оберіть кількість повторень:",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("reps:"))
async def process_reps(callback: CallbackQuery, state: FSMContext) -> None:
    """Process reps selection."""
    action = callback.data.split(":")[1]

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text("❌ Створення програми скасовано")
        await callback.answer()
        return

    reps = int(action)
    await state.update_data(current_reps=reps)
    await state.set_state(WorkoutProgramStates.comment)

    await callback.message.edit_text(
        f"✅ Повторень: *{reps}*\n\n"
        "Додайте коментар до вправи\n"
        "(або надішліть '-' щоб пропустити):",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(WorkoutProgramStates.comment)
async def process_comment(message: Message, state: FSMContext) -> None:
    """Process comment input and save exercise."""
    comment = message.text.strip() if message.text.strip() != "-" else ""

    data = await state.get_data()

    # Create exercise record
    exercise = {
        "muscle_group": data["current_muscle_group"],
        "exercise": data["current_exercise"],
        "sets": data["current_sets"],
        "reps": data["current_reps"],
        "comment": comment,
        "created_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }

    # Add to exercises list
    exercises = data.get("exercises", [])
    exercises.append(exercise)
    await state.update_data(exercises=exercises)

    await state.set_state(WorkoutProgramStates.add_more)

    # Show summary
    summary = f"✅ *Вправа додана!*\n\n"
    summary += f"🦴 Група: {exercise['muscle_group']}\n"
    summary += f"💪 Вправа: {exercise['exercise']}\n"
    summary += f"📊 Підходи × Повторення: {exercise['sets']} × {exercise['reps']}\n"
    if comment:
        summary += f"💬 Коментар: {comment}\n"

    summary += f"\n📝 Всього вправ у програмі: {len(exercises)}"

    keyboard = get_add_more_exercise_keyboard()
    await message.answer(summary, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data.startswith("program:"))
async def process_program_action(callback: CallbackQuery, state: FSMContext) -> None:
    """Process program actions (add more or finish)."""
    action = callback.data.split(":")[1]

    if action == "add_more":
        await state.set_state(WorkoutProgramStates.muscle_group)
        keyboard = get_muscle_group_keyboard()
        await callback.message.edit_text(
            "💪 Додайте ще одну вправу\n\n"
            "Оберіть групу м'язів:",
            reply_markup=keyboard,
        )
        await callback.answer()
        return

    if action == "finish":
        data = await state.get_data()
        exercises = data.get("exercises", [])

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
        summary = "✅ *Програма тренувань збережена!*\n\n"

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
    """View saved workout programs."""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас немає прав для цієї дії")
        return

    try:
        sheets_service = GoogleSheetsService()
        programs = await sheets_service.get_workout_programs()

        if not programs:
            await message.answer(
                "📋 *Програми тренувань*\n\n"
                "_Поки немає збережених програм_",
                parse_mode="Markdown",
            )
            return

        # Group by date
        text = "📋 *Останні програми тренувань:*\n\n"

        for i, program in enumerate(programs[-10:], 1):  # Last 10 records
            text += (
                f"{i}. {program.get('muscle_group', '-')} | "
                f"{program.get('exercise', '-')} | "
                f"{program.get('sets', '-')}×{program.get('reps', '-')}"
            )
            if program.get("comment"):
                text += f" | {program['comment']}"
            text += "\n"

        await message.answer(text, parse_mode="Markdown")

    except Exception as e:
        await message.answer(
            f"❌ Помилка при завантаженні програм: {str(e)}",
            parse_mode="Markdown",
        )
