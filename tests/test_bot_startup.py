"""Tests for bot startup helpers (src/bot/bot.py)."""

from unittest.mock import AsyncMock, MagicMock

from src.bot import bot as bot_module


class TestConfigureDefaultMenuButton:
    async def test_sets_global_menu_button_when_webapp_url_configured(self, monkeypatch):
        monkeypatch.setattr(bot_module.settings, "webapp_url", "https://example.com")
        bot = MagicMock()
        bot.set_chat_menu_button = AsyncMock()

        await bot_module.configure_default_menu_button(bot)

        bot.set_chat_menu_button.assert_awaited_once()
        _, kwargs = bot.set_chat_menu_button.call_args
        assert "chat_id" not in kwargs
        assert kwargs["menu_button"].text == "📱 Щоденник"
        assert kwargs["menu_button"].web_app.url == "https://example.com/nutrition"

    async def test_skips_when_webapp_url_missing(self, monkeypatch):
        monkeypatch.setattr(bot_module.settings, "webapp_url", "")
        bot = MagicMock()
        bot.set_chat_menu_button = AsyncMock()

        await bot_module.configure_default_menu_button(bot)

        bot.set_chat_menu_button.assert_not_awaited()
