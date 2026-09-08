"""Tests for the interactive calendar picker (src/bot/calendar_picker.py)."""

from datetime import datetime

import pytest

from src.bot import calendar_picker
from src.bot.calendar_picker import (
    create_calendar,
    create_duration_picker,
    create_participants_picker,
    create_time_picker,
    get_next_month,
    get_prev_month,
    process_calendar_callback,
)


class _FrozenDateTime(datetime):
    """A ``datetime`` subclass with a fixed ``now()``, so day-highlighting
    logic in ``create_calendar`` is deterministic without a freezegun
    dependency. Still behaves like a normal ``datetime`` otherwise.
    """

    _frozen = datetime(2026, 6, 15, 10, 0, 0)

    @classmethod
    def now(cls, tz=None):
        return cls._frozen


@pytest.fixture(autouse=True)
def _freeze_now(monkeypatch):
    monkeypatch.setattr(calendar_picker, "datetime", _FrozenDateTime)


def _flat_buttons(markup):
    return [btn for row in markup.inline_keyboard for btn in row]


class TestCreateCalendar:
    def test_defaults_to_current_year_and_month(self):
        keyboard = create_calendar()
        header = keyboard.inline_keyboard[0][1]
        assert header.text == "Червень 2026"

    def test_header_navigation_uses_given_prefix(self):
        keyboard = create_calendar(2026, 6, prefix="mycal")
        prev_btn, _, next_btn = keyboard.inline_keyboard[0]
        assert prev_btn.callback_data == "mycal:prev:2026:6"
        assert next_btn.callback_data == "mycal:next:2026:6"

    def test_weekday_header_row(self):
        keyboard = create_calendar(2026, 6)
        weekday_row = keyboard.inline_keyboard[1]
        assert [b.text for b in weekday_row] == calendar_picker.WEEKDAYS_UA

    def test_past_day_is_dimmed_and_not_clickable(self):
        # 2026-06-15 is "today"; June 10 is in the past.
        keyboard = create_calendar(2026, 6)
        buttons = _flat_buttons(keyboard)
        past_day = next(b for b in buttons if b.callback_data == calendar_picker.IGNORE_CALLBACK and b.text == "·")
        assert past_day.text == "·"

    def test_today_is_highlighted(self):
        keyboard = create_calendar(2026, 6)
        buttons = _flat_buttons(keyboard)
        today_btn = next(b for b in buttons if b.text == "[15]")
        assert today_btn.callback_data == "calendar:day:2026:6:15"

    def test_future_day_is_clickable(self):
        keyboard = create_calendar(2026, 6)
        buttons = _flat_buttons(keyboard)
        future_btn = next(b for b in buttons if b.callback_data == "calendar:day:2026:6:20")
        assert future_btn.text == "20"

    def test_cancel_button_is_last(self):
        keyboard = create_calendar(2026, 6)
        last_row = keyboard.inline_keyboard[-1]
        assert last_row[0].callback_data == "calendar:cancel"

    def test_empty_calendar_cells_are_padding(self):
        # June 2026 starts on a Monday, so no leading padding is expected;
        # a month starting mid-week (e.g. Sept 2026, starts Tuesday) does.
        keyboard = create_calendar(2026, 9)
        first_week = keyboard.inline_keyboard[2]
        assert first_week[0].text == " "
        assert first_week[0].callback_data == calendar_picker.IGNORE_CALLBACK


class TestCreateTimePicker:
    def test_includes_selected_date_header(self):
        keyboard = create_time_picker(datetime(2026, 6, 20))
        header = keyboard.inline_keyboard[0][0]
        assert header.text == "📅 20.06.2026"

    def test_generates_half_hour_slots_grouped_by_four(self):
        keyboard = create_time_picker(datetime(2026, 6, 20), start_hour=7, end_hour=7)
        # start_hour==end_hour=7 -> two slots: 07:00, 07:30 (one row)
        slot_row = keyboard.inline_keyboard[1]
        assert [b.text for b in slot_row] == ["07:00", "07:30"]

    def test_default_range_produces_expected_slot_count(self):
        keyboard = create_time_picker(datetime(2026, 6, 20))
        all_buttons = _flat_buttons(keyboard)
        slot_buttons = [b for b in all_buttons if b.callback_data.startswith("time:select:")]
        # 7..22 inclusive, 2 slots/hour = 16 * 2 = 32
        assert len(slot_buttons) == 32

    def test_back_and_cancel_row_present(self):
        keyboard = create_time_picker(datetime(2026, 6, 20), prefix="mytime")
        last_row = keyboard.inline_keyboard[-1]
        assert last_row[0].callback_data == "calendar:back:2026:6"
        assert last_row[1].callback_data == "mytime:cancel"


class TestCreateDurationPicker:
    def test_options_and_cancel(self):
        keyboard = create_duration_picker()
        buttons = _flat_buttons(keyboard)
        durations = [
            b.callback_data.split(":")[1]
            for b in buttons
            if b.callback_data.startswith("duration:") and b.callback_data != "duration:cancel"
        ]
        assert durations == ["30", "45", "60", "90", "120"]
        assert buttons[-1].callback_data == "duration:cancel"


class TestCreateParticipantsPicker:
    def test_options_and_cancel(self):
        keyboard = create_participants_picker()
        buttons = _flat_buttons(keyboard)
        counts = [
            b.callback_data.split(":")[1]
            for b in buttons
            if b.callback_data.startswith("participants:")
            and b.callback_data != "participants:cancel"
        ]
        assert counts == ["1", "2", "3", "4", "5", "6", "8", "10", "12", "15", "20", "25", "30"]
        assert buttons[-1].callback_data == "participants:cancel"


class TestProcessCalendarCallback:
    @pytest.mark.parametrize("action", ["prev", "next", "back"])
    def test_navigation_actions_parse_year_and_month(self, action):
        parsed_action, params = process_calendar_callback(f"calendar:{action}:2026:6")
        assert parsed_action == action
        assert params == {"year": 2026, "month": 6}

    def test_day_action_parses_full_date(self):
        action, params = process_calendar_callback("calendar:day:2026:6:15")
        assert action == "day"
        assert params == {"year": 2026, "month": 6, "day": 15}

    def test_select_action_parses_date_and_time(self):
        action, params = process_calendar_callback("time:select:2026:6:15:9:30")
        assert action == "select"
        assert params == {"year": 2026, "month": 6, "day": 15, "hour": 9, "minute": 30}

    def test_cancel_action_has_no_params(self):
        action, params = process_calendar_callback("calendar:cancel")
        assert action == "cancel"
        assert params == {}

    def test_unknown_format_does_not_raise(self):
        action, params = process_calendar_callback("calendar")
        assert action == ""
        assert params == {}


class TestMonthArithmetic:
    def test_get_next_month_within_year(self):
        assert get_next_month(2026, 6) == (2026, 7)

    def test_get_next_month_wraps_to_january(self):
        assert get_next_month(2026, 12) == (2027, 1)

    def test_get_prev_month_within_year(self):
        assert get_prev_month(2026, 6) == (2026, 5)

    def test_get_prev_month_wraps_to_december(self):
        assert get_prev_month(2026, 1) == (2025, 12)
