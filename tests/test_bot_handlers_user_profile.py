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
