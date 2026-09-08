"""Tests for the /nutrition command handler (src/bot/handlers/nutrition.py)."""

from src.bot.handlers import nutrition
from tests.bot_mocks import make_message


class TestCmdNutrition:
    async def test_warns_when_webapp_url_not_configured(self, monkeypatch):
        monkeypatch.setattr(nutrition.settings, "webapp_url", "")
        message = make_message(text="/nutrition")

        await nutrition.cmd_nutrition(message)

        message.answer.assert_awaited_once()
        (text,), kwargs = message.answer.call_args
        assert "не налаштовано" in text
        assert "reply_markup" not in kwargs

    async def test_sends_webapp_button_when_configured(self, monkeypatch):
        monkeypatch.setattr(nutrition.settings, "webapp_url", "https://example.com")
        message = make_message(text="/nutrition")

        await nutrition.cmd_nutrition(message)

        message.answer.assert_awaited_once()
        (text,), kwargs = message.answer.call_args
        assert "Трекер харчування" in text
        keyboard = kwargs["reply_markup"]
        button = keyboard.inline_keyboard[0][0]
        assert button.web_app.url == "https://example.com/nutrition"
