"""Keyboard layouts for the bot."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from src.config import get_settings
from src.database.models import GroupChat, Training
from src.services.workout_program_parsing import MUSCLE_GROUPS  # noqa: F401


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Get main menu keyboard (GYM-18/36).

    Rows opening the WebApp ("🍎 Харчування", "🏋️ Тренування",
    "📊 Статистика") are included only when ``WEBAPP_URL`` is configured —
    same guard as the default chat-menu button
    (``src/bot/bot.py: configure_bot_commands``) — so the keyboard still
    builds in environments without it (tests, local dev without a public
    URL); "🏋️ Тренування" opens ``/nutrition?tab=workout``, which the page
    reads to jump straight to its workout section instead of "Сьогодні".
    "📅 Розклад"/"📝 Мої записи" are plain reply-keyboard buttons for the
    group-booking flow, independent of the WebApp, so they're always shown.
    """
    settings = get_settings()
    buttons = []

    if settings.webapp_url:
        buttons.append([
            KeyboardButton(
                text="🍎 Харчування",
                web_app=WebAppInfo(url=f"{settings.webapp_url}/nutrition"),
            ),
            KeyboardButton(
                text="🏋️ Тренування",
                web_app=WebAppInfo(url=f"{settings.webapp_url}/nutrition?tab=workout"),
            ),
        ])
        buttons.append([
            KeyboardButton(
                text="📊 Статистика",
                web_app=WebAppInfo(url=f"{settings.webapp_url}/statistics"),
            ),
            KeyboardButton(text="👤 Профіль"),
        ])
    else:
        buttons.append([KeyboardButton(text="👤 Профіль")])

    buttons.append([
        KeyboardButton(text="📅 Розклад"),
        KeyboardButton(text="📝 Мої записи"),
    ])
    buttons.append([KeyboardButton(text="ℹ️ Допомога")])

    keyboard = ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
    )
    return keyboard


def get_admin_menu_keyboard() -> ReplyKeyboardMarkup:
    """Get admin menu keyboard (GYM-36).

    Trainer-only rows (program management, adding a training, the admin
    stats summary) on top of the regular main menu, so admins keep every
    button a regular user has — booking, nutrition/workout/statistics
    WebApp, profile — instead of losing them behind an admin-only keyboard.
    """
    admin_rows = [
        [
            KeyboardButton(text="💪 Програма тренувань"),
            KeyboardButton(text="📋 Переглянути програми"),
        ],
        [
            KeyboardButton(text="➕ Додати тренування"),
            KeyboardButton(text="📈 Адмін-статистика"),
        ],
    ]
    main_menu_rows = list(get_main_menu_keyboard().keyboard)

    keyboard = ReplyKeyboardMarkup(
        keyboard=admin_rows + main_menu_rows,
        resize_keyboard=True,
    )
    return keyboard


def get_user_selection_keyboard(users: list[str]) -> InlineKeyboardMarkup:
    """Get inline keyboard for user selection.

    Args:
        users: List of user names to select from

    Returns:
        Inline keyboard with user options
    """
    buttons = []
    for user_name in users:
        buttons.append(
            [InlineKeyboardButton(text=f"👤 {user_name}", callback_data=f"user:{user_name}")]
        )
    buttons.append(
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="user:cancel")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


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


def get_view_muscle_filter_keyboard(include_all: bool = True) -> InlineKeyboardMarkup:
    """Get inline keyboard for filtering by muscle group when viewing programs.

    Args:
        include_all: Whether to include 'All groups' option

    Returns:
        Inline keyboard with muscle group filter options
    """
    buttons = []
    if include_all:
        buttons.append(
            [InlineKeyboardButton(text="📋 Всі групи м'язів", callback_data="view_muscle:all")]
        )
    for group in MUSCLE_GROUPS:
        buttons.append(
            [InlineKeyboardButton(text=group, callback_data=f"view_muscle:{group}")]
        )
    buttons.append(
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="view_muscle:cancel")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_view_day_filter_keyboard(available_days: list[int]) -> InlineKeyboardMarkup:
    """Get inline keyboard for filtering by day when viewing programs.

    Args:
        available_days: List of available day numbers

    Returns:
        Inline keyboard with day filter options
    """
    buttons = []
    buttons.append(
        [InlineKeyboardButton(text="📋 Всі дні", callback_data="view_day:all")]
    )
    for day in sorted(available_days):
        buttons.append(
            [InlineKeyboardButton(text=f"📅 День {day}", callback_data=f"view_day:{day}")]
        )
    buttons.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="view_day:back")]
    )
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


def get_start_workout_keyboard(webapp_url: str) -> InlineKeyboardMarkup:
    """Get inline keyboard with Start Workout WebApp button.

    Args:
        webapp_url: Full URL for the workout WebApp including query params

    Returns:
        Inline keyboard with WebApp button
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text='🏋️ Почати тренування',
                    web_app=WebAppInfo(url=webapp_url),
                )
            ]
        ]
    )


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


# --- Group reminders (`/reminders`, GYM-33) ---

GROUP_REMINDER_TIME_CHOICES = ["07:00", "09:00", "12:00", "18:00", "20:00", "21:00"]
# Index == GroupChat.measurements_weekday (0 = Monday, matches Python's
# own date.weekday()).
GROUP_REMINDER_WEEKDAY_LABELS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
GROUP_REMINDER_DAY_OF_MONTH_CHOICES = [1, 15]

_GROUP_REMINDER_LABELS = {
    "nutrition": "🍽 Харчування",
    "measurements": "📏 Заміри",
    "photos": "📸 Фото прогресу",
}


def _group_reminder_schedule_text(reminder_type: str, group: GroupChat) -> str:
    """Human-readable schedule fragment for one reminder type's toggle
    button label, e.g. "щодня 20:00", "пн 09:00", "1-го числа 09:00".
    """
    if reminder_type == "nutrition":
        return f"щодня {group.nutrition_time}"
    if reminder_type == "measurements":
        weekday_label = GROUP_REMINDER_WEEKDAY_LABELS[group.measurements_weekday].lower()
        return f"{weekday_label} {group.measurements_time}"
    if reminder_type == "photos":
        return f"{group.photos_day_of_month}-го числа {group.photos_time}"
    raise ValueError(f"Unknown reminder_type: {reminder_type!r}")


def get_group_reminders_panel_keyboard(group: GroupChat) -> InlineKeyboardMarkup:
    """Main `/reminders` panel (GYM-33): one toggle + "⏰ Час…" row pair
    per reminder type. The toggle button's own text carries the current
    schedule and on/off state (`grem:toggle:<type>` flips it in place);
    "⏰ Час…" (`grem:time:<type>`) opens that type's time-choice submenu
    (:func:`get_group_reminders_time_keyboard`).
    """
    enabled_by_type = {
        "nutrition": group.remind_nutrition,
        "measurements": group.remind_measurements,
        "photos": group.remind_photos,
    }
    buttons = []
    for reminder_type, label in _GROUP_REMINDER_LABELS.items():
        state_icon = "✅" if enabled_by_type[reminder_type] else "❌"
        schedule = _group_reminder_schedule_text(reminder_type, group)
        buttons.append([
            InlineKeyboardButton(
                text=f"{label} · {schedule} [{state_icon}]",
                callback_data=f"grem:toggle:{reminder_type}",
            ),
            InlineKeyboardButton(
                text="⏰ Час…", callback_data=f"grem:time:{reminder_type}",
            ),
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_group_reminders_time_keyboard(reminder_type: str) -> InlineKeyboardMarkup:
    """Time-choice submenu for one reminder type (GYM-33) — a row of time
    chips (`grem:settime:<type>:<HH:MM>`), plus, for "measurements", a
    weekday row (`grem:setweekday:<0-6>`) and, for "photos", a
    day-of-month row (`grem:setday:<1|15>`); always ends with "⬅️ Назад"
    (`grem:back`) to return to the main panel.
    """
    rows = []
    time_row = [
        InlineKeyboardButton(text=t, callback_data=f"grem:settime:{reminder_type}:{t}")
        for t in GROUP_REMINDER_TIME_CHOICES
    ]
    # 3 per row keeps each button legibly wide on a phone screen.
    for i in range(0, len(time_row), 3):
        rows.append(time_row[i:i + 3])

    if reminder_type == "measurements":
        rows.append([
            InlineKeyboardButton(text=label, callback_data=f"grem:setweekday:{i}")
            for i, label in enumerate(GROUP_REMINDER_WEEKDAY_LABELS)
        ])
    elif reminder_type == "photos":
        rows.append([
            InlineKeyboardButton(text=f"{d}-го", callback_data=f"grem:setday:{d}")
            for d in GROUP_REMINDER_DAY_OF_MONTH_CHOICES
        ])

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="grem:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
