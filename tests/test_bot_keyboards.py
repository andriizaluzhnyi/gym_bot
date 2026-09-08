"""Tests for keyboard layouts (src/bot/keyboards.py)."""

from types import SimpleNamespace

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from src.bot import keyboards


def _flat_buttons(markup: InlineKeyboardMarkup) -> list:
    return [btn for row in markup.inline_keyboard for btn in row]


def _make_training(
    *, training_id=1, title="Йога", scheduled_at=None, location=None, description=None,
    max_participants=10, confirmed_bookings=0,
):
    """A duck-typed stand-in for the ``Training`` model.

    The keyboards only read plain attributes, so a lightweight
    ``SimpleNamespace`` (with ``available_spots`` precomputed, matching the
    real model's property) is enough — no DB/session needed for these tests.
    """
    from datetime import datetime

    return SimpleNamespace(
        id=training_id,
        title=title,
        scheduled_at=scheduled_at or datetime(2026, 6, 15, 18, 0),
        location=location,
        description=description,
        max_participants=max_participants,
        available_spots=max(0, max_participants - confirmed_bookings),
    )


class TestMainMenuKeyboards:
    def test_main_menu_has_profile_and_help(self):
        keyboard = keyboards.get_main_menu_keyboard()
        assert isinstance(keyboard, ReplyKeyboardMarkup)
        texts = [btn.text for row in keyboard.keyboard for btn in row]
        assert "👤 Профіль" in texts
        assert "ℹ️ Допомога" in texts

    def test_admin_menu_adds_program_buttons(self):
        keyboard = keyboards.get_admin_menu_keyboard()
        texts = [btn.text for row in keyboard.keyboard for btn in row]
        assert "💪 Програма тренувань" in texts
        assert "📋 Переглянути програми" in texts
        assert "👤 Профіль" in texts


class TestUserSelectionKeyboard:
    def test_lists_each_user_and_a_cancel_button(self):
        keyboard = keyboards.get_user_selection_keyboard(["andrii", "olena"])
        buttons = _flat_buttons(keyboard)

        assert [b.callback_data for b in buttons] == [
            "user:andrii", "user:olena", "user:cancel",
        ]

    def test_empty_list_still_has_cancel(self):
        keyboard = keyboards.get_user_selection_keyboard([])
        buttons = _flat_buttons(keyboard)
        assert len(buttons) == 1
        assert buttons[0].callback_data == "user:cancel"


class TestMuscleGroupKeyboard:
    def test_contains_all_muscle_groups_and_cancel(self):
        keyboard = keyboards.get_muscle_group_keyboard()
        buttons = _flat_buttons(keyboard)
        callback_data = [b.callback_data for b in buttons]

        for group in keyboards.MUSCLE_GROUPS:
            assert f"muscle:{group}" in callback_data
        assert callback_data[-1] == "muscle:cancel"


class TestRepsAndSetsKeyboards:
    def test_reps_keyboard_options(self):
        keyboard = keyboards.get_reps_keyboard()
        buttons = _flat_buttons(keyboard)
        reps_values = [
            b.callback_data.split(":")[1]
            for b in buttons
            if b.callback_data.startswith("reps:") and b.callback_data != "reps:cancel"
        ]
        assert reps_values == ["5", "8", "10", "12", "15", "20", "25", "30"]

    def test_sets_keyboard_options(self):
        keyboard = keyboards.get_sets_keyboard()
        buttons = _flat_buttons(keyboard)
        sets_values = [
            b.callback_data.split(":")[1]
            for b in buttons
            if b.callback_data.startswith("sets:") and b.callback_data != "sets:cancel"
        ]
        assert sets_values == ["1", "2", "3", "4", "5"]

    def test_sets_reps_keyboard_has_quick_combos_and_cancel(self):
        keyboard = keyboards.get_sets_reps_keyboard()
        buttons = _flat_buttons(keyboard)
        assert buttons[-1].callback_data == "setsreps:cancel"
        assert "setsreps:3/10" in [b.callback_data for b in buttons]


class TestAddMoreExerciseKeyboard:
    def test_has_add_and_finish_options(self):
        keyboard = keyboards.get_add_more_exercise_keyboard()
        buttons = _flat_buttons(keyboard)
        assert [b.callback_data for b in buttons] == [
            "program:add_more", "program:finish",
        ]


class TestViewFilterKeyboards:
    def test_muscle_filter_includes_all_option_by_default(self):
        keyboard = keyboards.get_view_muscle_filter_keyboard()
        buttons = _flat_buttons(keyboard)
        assert buttons[0].callback_data == "view_muscle:all"
        assert buttons[-1].callback_data == "view_muscle:cancel"

    def test_muscle_filter_can_omit_all_option(self):
        keyboard = keyboards.get_view_muscle_filter_keyboard(include_all=False)
        buttons = _flat_buttons(keyboard)
        assert buttons[0].callback_data != "view_muscle:all"

    def test_day_filter_sorts_days_and_has_all_and_back(self):
        keyboard = keyboards.get_view_day_filter_keyboard([3, 1, 2])
        buttons = _flat_buttons(keyboard)
        callback_data = [b.callback_data for b in buttons]
        assert callback_data[0] == "view_day:all"
        assert callback_data[1:-1] == ["view_day:1", "view_day:2", "view_day:3"]
        assert callback_data[-1] == "view_day:back"


class TestDaySelectionKeyboard:
    def test_no_existing_days_only_offers_day_one(self):
        keyboard = keyboards.get_day_selection_keyboard(last_day=0)
        buttons = _flat_buttons(keyboard)
        callback_data = [b.callback_data for b in buttons]
        assert callback_data == ["day:new:1", "day:cancel"]

    def test_existing_day_offers_continue_and_next_new_day(self):
        keyboard = keyboards.get_day_selection_keyboard(last_day=2)
        buttons = _flat_buttons(keyboard)
        callback_data = [b.callback_data for b in buttons]
        assert callback_data == ["day:continue:2", "day:new:3", "day:cancel"]


class TestStartWorkoutKeyboard:
    def test_webapp_button_points_to_given_url(self):
        keyboard = keyboards.get_start_workout_keyboard(
            "https://example.com/workout?user=andrii"
        )
        button = keyboard.inline_keyboard[0][0]
        assert button.web_app.url == "https://example.com/workout?user=andrii"
        assert button.text == '🏋️ Почати тренування'


class TestPhoneRequestKeyboard:
    def test_has_share_contact_and_skip(self):
        keyboard = keyboards.get_phone_request_keyboard()
        assert isinstance(keyboard, ReplyKeyboardMarkup)
        texts = [btn.text for row in keyboard.keyboard for btn in row]
        assert "📱 Поділитися номером" in texts
        assert "⏭️ Пропустити" in texts
        share_btn = keyboard.keyboard[0][0]
        assert share_btn.request_contact is True


class TestScheduleKeyboard:
    def test_lists_trainings_with_availability_status(self):
        full = _make_training(training_id=1, title="Йога", max_participants=1, confirmed_bookings=1)
        open_ = _make_training(training_id=2, title="Бокс", max_participants=5, confirmed_bookings=0)

        keyboard = keyboards.get_schedule_inline_keyboard([full, open_])
        buttons = _flat_buttons(keyboard)

        assert buttons[0].text.startswith("❌")
        assert buttons[0].callback_data == "training:1"
        assert buttons[1].text.startswith("✅")
        assert buttons[1].callback_data == "training:2"

    def test_empty_list_shows_placeholder(self):
        keyboard = keyboards.get_schedule_inline_keyboard([])
        buttons = _flat_buttons(keyboard)
        assert len(buttons) == 1
        assert buttons[0].callback_data == "no_trainings"


class TestTrainingDetailKeyboard:
    def test_user_with_booking_can_cancel(self):
        training = _make_training(training_id=7)
        keyboard = keyboards.get_training_detail_keyboard(training, user_has_booking=True)
        buttons = _flat_buttons(keyboard)
        assert buttons[0].callback_data == "cancel_booking:7"
        assert buttons[-1].callback_data == "back_to_schedule"

    def test_open_spot_offers_booking(self):
        training = _make_training(training_id=7, max_participants=5, confirmed_bookings=0)
        keyboard = keyboards.get_training_detail_keyboard(training, user_has_booking=False)
        buttons = _flat_buttons(keyboard)
        assert buttons[0].callback_data == "book:7"

    def test_full_training_offers_notify(self):
        training = _make_training(training_id=7, max_participants=1, confirmed_bookings=1)
        keyboard = keyboards.get_training_detail_keyboard(training, user_has_booking=False)
        buttons = _flat_buttons(keyboard)
        assert buttons[0].callback_data == "notify_spot:7"


class TestBookingKeyboards:
    def test_booking_confirmation_keyboard(self):
        keyboard = keyboards.get_booking_confirmation_keyboard(42)
        buttons = _flat_buttons(keyboard)
        assert buttons[0].callback_data == "cancel_booking_id:42"
        assert buttons[1].callback_data == "back_to_schedule"

    def test_my_bookings_lists_each_booking(self):
        training = _make_training(training_id=1, title="Йога")
        booking = SimpleNamespace(id=99, training=training)

        keyboard = keyboards.get_my_bookings_keyboard([booking])
        buttons = _flat_buttons(keyboard)
        assert buttons[0].callback_data == "my_booking:99"

    def test_my_bookings_empty_shows_placeholder_and_schedule_link(self):
        keyboard = keyboards.get_my_bookings_keyboard([])
        buttons = _flat_buttons(keyboard)
        assert buttons[0].callback_data == "no_bookings"
        assert buttons[1].callback_data == "back_to_schedule"


class TestAdminKeyboards:
    def test_admin_training_keyboard(self):
        training = _make_training(training_id=3)
        keyboard = keyboards.get_admin_training_keyboard(training)
        buttons = _flat_buttons(keyboard)
        callback_data = [b.callback_data for b in buttons]
        assert callback_data == [
            "admin_participants:3", "admin_edit:3", "admin_cancel:3", "admin_back",
        ]

    def test_confirm_cancel_keyboard(self):
        keyboard = keyboards.get_confirm_cancel_keyboard(5)
        buttons = _flat_buttons(keyboard)
        assert buttons[0].callback_data == "confirm_cancel:5"
        assert buttons[1].callback_data == "training:5"
