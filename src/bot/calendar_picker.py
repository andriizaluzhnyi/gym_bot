"""Interactive calendar picker for Telegram bot."""

import calendar
from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Ukrainian month names
MONTHS_UA = [
    "",
    "Січень",
    "Лютий",
    "Березень",
    "Квітень",
    "Травень",
    "Червень",
    "Липень",
    "Серпень",
    "Вересень",
    "Жовтень",
    "Листопад",
    "Грудень",
]

# Ukrainian weekday names (short)
WEEKDAYS_UA = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]

# Callback data prefixes
CALENDAR_CALLBACK = "calendar"
TIME_CALLBACK = "time"
IGNORE_CALLBACK = "ignore"


def create_calendar(
    year: int | None = None,
    month: int | None = None,
    prefix: str = CALENDAR_CALLBACK,
) -> InlineKeyboardMarkup:
    """Create an inline keyboard with a calendar.

    Args:
        year: Year to display (default: current year)
        month: Month to display (default: current month)
        prefix: Callback data prefix

    Returns:
        InlineKeyboardMarkup with calendar
    """
    now = datetime.now()
    if year is None:
        year = now.year
    if month is None:
        month = now.month

    keyboard = []

    # Month and year header with navigation
    row = [
        InlineKeyboardButton(text="◀️", callback_data=f"{prefix}:prev:{year}:{month}"),
        InlineKeyboardButton(
            text=f"{MONTHS_UA[month]} {year}",
            callback_data=IGNORE_CALLBACK,
        ),
        InlineKeyboardButton(text="▶️", callback_data=f"{prefix}:next:{year}:{month}"),
    ]
    keyboard.append(row)

    # Weekday headers
    row = [
        InlineKeyboardButton(text=day, callback_data=IGNORE_CALLBACK)
        for day in WEEKDAYS_UA
    ]
    keyboard.append(row)

    # Calendar days
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(
                    InlineKeyboardButton(text=" ", callback_data=IGNORE_CALLBACK)
                )
            else:
                # Check if date is in the past
                date = datetime(year, month, day)
                if date.date() < now.date():
                    row.append(
                        InlineKeyboardButton(text="·", callback_data=IGNORE_CALLBACK)
                    )
                else:
                    # Highlight today
                    day_text = f"[{day}]" if date.date() == now.date() else str(day)
                    row.append(
                        InlineKeyboardButton(
                            text=day_text,
                            callback_data=f"{prefix}:day:{year}:{month}:{day}",
                        )
                    )
        keyboard.append(row)

    # Cancel button
    keyboard.append(
        [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"{prefix}:cancel")]
    )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def create_time_picker(
    selected_date: datetime,
    prefix: str = TIME_CALLBACK,
    start_hour: int = 7,
    end_hour: int = 22,
) -> InlineKeyboardMarkup:
    """Create an inline keyboard for time selection.

    Args:
        selected_date: The selected date
        prefix: Callback data prefix
        start_hour: First available hour
        end_hour: Last available hour

    Returns:
        InlineKeyboardMarkup with time slots
    """
    keyboard = []

    date_str = selected_date.strftime("%d.%m.%Y")
    keyboard.append(
        [InlineKeyboardButton(text=f"📅 {date_str}", callback_data=IGNORE_CALLBACK)]
    )

    # Generate time slots (every 30 minutes)
    row = []
    for hour in range(start_hour, end_hour + 1):
        for minute in [0, 30]:
            time_str = f"{hour:02d}:{minute:02d}"
            callback = f"{prefix}:select:{selected_date.year}:{selected_date.month}:{selected_date.day}:{hour}:{minute}"
            row.append(InlineKeyboardButton(text=time_str, callback_data=callback))

            if len(row) == 4:
                keyboard.append(row)
                row = []

    if row:
        keyboard.append(row)

    # Back and cancel buttons
    keyboard.append(
        [
            InlineKeyboardButton(
                text="◀️ Назад",
                callback_data=f"calendar:back:{selected_date.year}:{selected_date.month}",
            ),
            InlineKeyboardButton(text="❌ Скасувати", callback_data=f"{prefix}:cancel"),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def create_duration_picker(prefix: str = "duration") -> InlineKeyboardMarkup:
    """Create an inline keyboard for duration selection.

    Args:
        prefix: Callback data prefix

    Returns:
        InlineKeyboardMarkup with duration options
    """
    keyboard = [
        [InlineKeyboardButton(text="⏱️ Оберіть тривалість:", callback_data=IGNORE_CALLBACK)],
        [
            InlineKeyboardButton(text="30 хв", callback_data=f"{prefix}:30"),
            InlineKeyboardButton(text="45 хв", callback_data=f"{prefix}:45"),
            InlineKeyboardButton(text="60 хв", callback_data=f"{prefix}:60"),
        ],
        [
            InlineKeyboardButton(text="90 хв", callback_data=f"{prefix}:90"),
            InlineKeyboardButton(text="120 хв", callback_data=f"{prefix}:120"),
        ],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"{prefix}:cancel")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def create_participants_picker(prefix: str = "participants") -> InlineKeyboardMarkup:
    """Create an inline keyboard for max participants selection.

    Args:
        prefix: Callback data prefix

    Returns:
        InlineKeyboardMarkup with participant count options
    """
    keyboard = [
        [InlineKeyboardButton(text="👥 Кількість учасників:", callback_data=IGNORE_CALLBACK)],
        [
            InlineKeyboardButton(text="1", callback_data=f"{prefix}:1"),
            InlineKeyboardButton(text="2", callback_data=f"{prefix}:2"),
            InlineKeyboardButton(text="3", callback_data=f"{prefix}:3"),
            InlineKeyboardButton(text="4", callback_data=f"{prefix}:4"),
            InlineKeyboardButton(text="5", callback_data=f"{prefix}:5"),
        ],
        [
            InlineKeyboardButton(text="6", callback_data=f"{prefix}:6"),
            InlineKeyboardButton(text="8", callback_data=f"{prefix}:8"),
            InlineKeyboardButton(text="10", callback_data=f"{prefix}:10"),
            InlineKeyboardButton(text="12", callback_data=f"{prefix}:12"),
            InlineKeyboardButton(text="15", callback_data=f"{prefix}:15"),
        ],
        [
            InlineKeyboardButton(text="20", callback_data=f"{prefix}:20"),
            InlineKeyboardButton(text="25", callback_data=f"{prefix}:25"),
            InlineKeyboardButton(text="30", callback_data=f"{prefix}:30"),
        ],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"{prefix}:cancel")],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def process_calendar_callback(callback_data: str) -> tuple[str, dict]:
    """Parse calendar callback data.

    Args:
        callback_data: Callback data string

    Returns:
        Tuple of (action, params dict)
    """
    parts = callback_data.split(":")
    prefix = parts[0]
    action = parts[1] if len(parts) > 1 else ""

    params = {}
    if action in ["prev", "next", "back"]:
        params["year"] = int(parts[2])
        params["month"] = int(parts[3])
    elif action == "day":
        params["year"] = int(parts[2])
        params["month"] = int(parts[3])
        params["day"] = int(parts[4])
    elif action == "select":
        params["year"] = int(parts[2])
        params["month"] = int(parts[3])
        params["day"] = int(parts[4])
        params["hour"] = int(parts[5])
        params["minute"] = int(parts[6])

    return action, params


def get_next_month(year: int, month: int) -> tuple[int, int]:
    """Get next month and year."""
    if month == 12:
        return year + 1, 1
    return year, month + 1


def get_prev_month(year: int, month: int) -> tuple[int, int]:
    """Get previous month and year."""
    if month == 1:
        return year - 1, 12
    return year, month - 1
