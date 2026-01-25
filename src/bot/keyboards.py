"""Keyboard layouts for the bot."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from src.database.models import Training


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Get main menu keyboard."""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📅 Розклад"),
                KeyboardButton(text="📝 Мої записи"),
            ],
            [
                KeyboardButton(text="👤 Профіль"),
                KeyboardButton(text="ℹ️ Допомога"),
            ],
        ],
        resize_keyboard=True,
    )
    return keyboard


def get_admin_menu_keyboard() -> ReplyKeyboardMarkup:
    """Get admin menu keyboard."""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📅 Розклад"),
                KeyboardButton(text="📝 Мої записи"),
            ],
            [
                KeyboardButton(text="➕ Додати тренування"),
                KeyboardButton(text="📊 Статистика"),
            ],
            [
                KeyboardButton(text="💪 Програма тренувань"),
                KeyboardButton(text="📋 Переглянути програми"),
            ],
            [
                KeyboardButton(text="👤 Профіль"),
                KeyboardButton(text="ℹ️ Допомога"),
            ],
        ],
        resize_keyboard=True,
    )
    return keyboard


# Muscle groups for workout program
MUSCLE_GROUPS = ["🦴 Спина", "💪 Руки", "🎯 Плечі", "🏋️ Груди", "🦵 Ноги"]


def get_muscle_group_keyboard() -> InlineKeyboardMarkup:
    """Get inline keyboard for muscle group selection."""
    buttons = []
    for group in MUSCLE_GROUPS:
        buttons.append(
            [InlineKeyboardButton(text=group, callback_data=f"muscle:{group}")]
        )
    buttons.append(
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="muscle:cancel")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_reps_keyboard() -> InlineKeyboardMarkup:
    """Get inline keyboard for repetitions selection."""
    buttons = [
        [InlineKeyboardButton(text="🔢 Оберіть кількість повторень:", callback_data="ignore")],
        [
            InlineKeyboardButton(text="5", callback_data="reps:5"),
            InlineKeyboardButton(text="8", callback_data="reps:8"),
            InlineKeyboardButton(text="10", callback_data="reps:10"),
            InlineKeyboardButton(text="12", callback_data="reps:12"),
        ],
        [
            InlineKeyboardButton(text="15", callback_data="reps:15"),
            InlineKeyboardButton(text="20", callback_data="reps:20"),
            InlineKeyboardButton(text="25", callback_data="reps:25"),
            InlineKeyboardButton(text="30", callback_data="reps:30"),
        ],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="reps:cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_sets_keyboard() -> InlineKeyboardMarkup:
    """Get inline keyboard for sets selection."""
    buttons = [
        [InlineKeyboardButton(text="📊 Оберіть кількість підходів:", callback_data="ignore")],
        [
            InlineKeyboardButton(text="1", callback_data="sets:1"),
            InlineKeyboardButton(text="2", callback_data="sets:2"),
            InlineKeyboardButton(text="3", callback_data="sets:3"),
            InlineKeyboardButton(text="4", callback_data="sets:4"),
            InlineKeyboardButton(text="5", callback_data="sets:5"),
        ],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="sets:cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_sets_reps_keyboard() -> InlineKeyboardMarkup:
    """Get inline keyboard for combined sets/reps selection.

    Provides quick options and allows manual text input.
    """
    buttons = [
        [
            InlineKeyboardButton(text="3/10", callback_data="setsreps:3/10"),
            InlineKeyboardButton(text="3/12", callback_data="setsreps:3/12"),
            InlineKeyboardButton(text="3/15", callback_data="setsreps:3/15"),
        ],
        [
            InlineKeyboardButton(text="4/8", callback_data="setsreps:4/8"),
            InlineKeyboardButton(text="4/10", callback_data="setsreps:4/10"),
            InlineKeyboardButton(text="4/12", callback_data="setsreps:4/12"),
        ],
        [
            InlineKeyboardButton(text="4/15", callback_data="setsreps:4/15"),
            InlineKeyboardButton(text="5/5", callback_data="setsreps:5/5"),
            InlineKeyboardButton(text="5/10", callback_data="setsreps:5/10"),
        ],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="setsreps:cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_add_more_exercise_keyboard() -> InlineKeyboardMarkup:
    """Get keyboard to add more exercises or finish."""
    buttons = [
        [InlineKeyboardButton(text="➕ Додати ще вправу", callback_data="program:add_more")],
        [InlineKeyboardButton(text="✅ Завершити програму", callback_data="program:finish")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_day_selection_keyboard(last_day: int = 0) -> InlineKeyboardMarkup:
    """Get keyboard for day selection.

    Args:
        last_day: Last existing day number (0 if no days exist)

    Returns:
        Inline keyboard with day options
    """
    buttons = []

    # Show existing days to continue
    if last_day > 0:
        buttons.append(
            [InlineKeyboardButton(
                text=f"📝 Продовжити День {last_day}",
                callback_data=f"day:continue:{last_day}"
            )]
        )

    # New day option
    new_day = last_day + 1
    buttons.append(
        [InlineKeyboardButton(
            text=f"➕ Створити День {new_day}",
            callback_data=f"day:new:{new_day}"
        )]
    )

    # Cancel
    buttons.append(
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="day:cancel")]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_phone_request_keyboard() -> ReplyKeyboardMarkup:
    """Get keyboard for phone number request."""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поділитися номером", request_contact=True)],
            [KeyboardButton(text="⏭️ Пропустити")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    return keyboard


def get_schedule_inline_keyboard(trainings: list[Training]) -> InlineKeyboardMarkup:
    """Get inline keyboard with available trainings."""
    buttons = []
    for training in trainings:
        time_str = training.scheduled_at.strftime("%d.%m %H:%M")
        spots = training.available_spots
        status = "✅" if spots > 0 else "❌"
        button_text = f"{status} {time_str} - {training.title} ({spots} місць)"
        buttons.append(
            [InlineKeyboardButton(text=button_text, callback_data=f"training:{training.id}")]
        )

    if not buttons:
        buttons.append(
            [InlineKeyboardButton(text="Немає доступних тренувань", callback_data="no_trainings")]
        )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_training_detail_keyboard(
    training: Training, user_has_booking: bool = False
) -> InlineKeyboardMarkup:
    """Get inline keyboard for training details."""
    buttons = []

    if user_has_booking:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="❌ Скасувати запис",
                    callback_data=f"cancel_booking:{training.id}",
                )
            ]
        )
    elif training.available_spots > 0:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="✅ Записатися",
                    callback_data=f"book:{training.id}",
                )
            ]
        )
    else:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="🔔 Сповістити про місце",
                    callback_data=f"notify_spot:{training.id}",
                )
            ]
        )

    buttons.append(
        [InlineKeyboardButton(text="⬅️ Назад до розкладу", callback_data="back_to_schedule")]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_booking_confirmation_keyboard(booking_id: int) -> InlineKeyboardMarkup:
    """Get confirmation keyboard after booking."""
    buttons = [
        [
            InlineKeyboardButton(
                text="❌ Скасувати запис",
                callback_data=f"cancel_booking_id:{booking_id}",
            )
        ],
        [InlineKeyboardButton(text="📅 Переглянути розклад", callback_data="back_to_schedule")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_my_bookings_keyboard(bookings: list) -> InlineKeyboardMarkup:
    """Get inline keyboard with user's bookings."""
    buttons = []
    for booking in bookings:
        training = booking.training
        time_str = training.scheduled_at.strftime("%d.%m %H:%M")
        button_text = f"📌 {time_str} - {training.title}"
        buttons.append(
            [InlineKeyboardButton(text=button_text, callback_data=f"my_booking:{booking.id}")]
        )

    if not buttons:
        buttons.append(
            [InlineKeyboardButton(text="У вас немає записів", callback_data="no_bookings")]
        )
        buttons.append(
            [InlineKeyboardButton(text="📅 Переглянути розклад", callback_data="back_to_schedule")]
        )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_admin_training_keyboard(training: Training) -> InlineKeyboardMarkup:
    """Get admin keyboard for training management."""
    buttons = [
        [
            InlineKeyboardButton(
                text="👥 Список учасників",
                callback_data=f"admin_participants:{training.id}",
            )
        ],
        [
            InlineKeyboardButton(
                text="✏️ Редагувати",
                callback_data=f"admin_edit:{training.id}",
            ),
            InlineKeyboardButton(
                text="🗑️ Скасувати",
                callback_data=f"admin_cancel:{training.id}",
            ),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_confirm_cancel_keyboard(training_id: int) -> InlineKeyboardMarkup:
    """Get confirmation keyboard for cancelling training."""
    buttons = [
        [
            InlineKeyboardButton(
                text="✅ Так, скасувати",
                callback_data=f"confirm_cancel:{training_id}",
            ),
            InlineKeyboardButton(
                text="❌ Ні",
                callback_data=f"training:{training_id}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
