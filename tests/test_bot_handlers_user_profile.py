"""Tests for the WebApp entry points in profile handlers
(src/bot/handlers/user_profile.py, GYM-35).
"""

import uuid

import pytest

from src.bot.handlers import user_profile
from src.database.models import Base
from src.database.repository import UserRepository
from src.database.session import async_session_maker, engine
from tests.bot_mocks import make_callback, make_telegram_user


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


def _unique_telegram_id() -> int:
    return uuid.uuid4().int % (2**31)


class TestProfileSettingsKeyboard:
    def test_webapp_button_when_url_configured(self, monkeypatch):
        monkeypatch.setattr(user_profile.settings, "webapp_url", "https://example.com")

        keyboard = user_profile.get_profile_settings_keyboard()

        goals_btn, webapp_btn = (row[0] for row in keyboard.inline_keyboard)
        assert goals_btn.text == "🎯 Цілі харчування"
        assert webapp_btn.text == "📱 Відкрити щоденник"
        assert webapp_btn.web_app.url == "https://example.com/nutrition"
        assert webapp_btn.callback_data is None

    def test_callback_fallback_when_url_missing(self, monkeypatch):
        monkeypatch.setattr(user_profile.settings, "webapp_url", "")

        keyboard = user_profile.get_profile_settings_keyboard()

        _, webapp_btn = (row[0] for row in keyboard.inline_keyboard)
        assert webapp_btn.callback_data == "profile:open_webapp"
        assert webapp_btn.web_app is None


class TestOpenWebappCallback:
    async def test_answers_not_configured(self, monkeypatch):
        # Reachable only in this state (see get_profile_settings_keyboard):
        # once WEBAPP_URL is set, the button carries a web_app payload
        # instead of callback_data and this handler never fires.
        monkeypatch.setattr(user_profile.settings, "webapp_url", "")
        callback = make_callback(data="profile:open_webapp")

        await user_profile.open_webapp_callback(callback)

        callback.answer.assert_awaited_once_with("Web App не налаштований", show_alert=True)


class TestNutritionSettingsText:
    async def test_uses_goals_heading(self):
        telegram_id = _unique_telegram_id()
        async with async_session_maker() as session:
            await UserRepository(session).get_or_create(
                telegram_id=telegram_id, first_name="Andrii"
            )
            await session.commit()

        callback = make_callback(
            data="profile:edit_nutrition",
            from_user=make_telegram_user(user_id=telegram_id),
        )

        await user_profile.show_nutrition_settings(callback)

        callback.message.edit_text.assert_awaited_once()
        (text,), _ = callback.message.edit_text.call_args
        assert "Цілі харчування" in text
        assert "Налаштування БЖУ" not in text

    async def test_shows_goal_value_when_water_tracking_enabled(self):
        nutrition = {
            "age": None, "height": None, "weight": None, "gender": None,
            "water_tracking_enabled": True,
            "daily_water_ml": 2500, "daily_calories": 2500,
            "daily_protein": 150, "daily_fats": 80, "daily_carbs": 250,
        }
        text = user_profile._format_nutrition_settings(nutrition)
        assert "💧 Вода: 2500 мл" in text
        assert "вимкнено" not in text

    async def test_shows_disabled_instead_of_goal_when_water_tracking_off(self):
        """GYM-25."""
        nutrition = {
            "age": None, "height": None, "weight": None, "gender": None,
            "water_tracking_enabled": False,
            "daily_water_ml": 2500, "daily_calories": 2500,
            "daily_protein": 150, "daily_fats": 80, "daily_carbs": 250,
        }
        text = user_profile._format_nutrition_settings(nutrition)
        assert "💧 Вода: вимкнено" in text
        assert "2500 мл" not in text


class TestNutritionSettingsKeyboardWaterButton:
    """GYM-25: the water button's callback/text depends on whether
    tracking is currently enabled.
    """

    def test_normal_edit_button_when_enabled(self):
        keyboard = user_profile.get_nutrition_settings_keyboard(
            water_tracking_enabled=True
        )
        buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        water_btn = next(b for b in buttons if b.callback_data in ("edit:water", "edit:water_toggle"))
        assert water_btn.callback_data == "edit:water"
        assert water_btn.text == "💧 Денна норма води"

    def test_offers_to_enable_when_disabled(self):
        keyboard = user_profile.get_nutrition_settings_keyboard(
            water_tracking_enabled=False
        )
        buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        water_btn = next(b for b in buttons if b.callback_data in ("edit:water", "edit:water_toggle"))
        assert water_btn.callback_data == "edit:water_toggle"
        assert "Увімкнути" in water_btn.text


class TestEnableWaterTracking:
    async def test_re_enables_and_shows_updated_settings(self):
        telegram_id = _unique_telegram_id()
        async with async_session_maker() as session:
            user_repo = UserRepository(session)
            user, _ = await user_repo.get_or_create(
                telegram_id=telegram_id, first_name="Andrii"
            )
            await user_repo.update_nutrition_settings(
                telegram_id, water_tracking_enabled=False
            )
            await session.commit()

        callback = make_callback(
            data="edit:water_toggle",
            from_user=make_telegram_user(user_id=telegram_id),
        )

        await user_profile.enable_water_tracking(callback)

        callback.message.edit_text.assert_awaited_once()
        (text,), kwargs = callback.message.edit_text.call_args
        assert "вимкнено" not in text
        water_btn = next(
            b for row in kwargs["reply_markup"].inline_keyboard for b in row
            if b.callback_data in ("edit:water", "edit:water_toggle")
        )
        assert water_btn.callback_data == "edit:water"
        callback.answer.assert_awaited_once()

        async with async_session_maker() as session:
            nutrition = await UserRepository(session).get_nutrition_settings(telegram_id)
        assert nutrition["water_tracking_enabled"] is True
