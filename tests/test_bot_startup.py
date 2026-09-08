"""Tests for bot startup helpers (src/bot/bot.py, GYM-35/36)."""

from unittest.mock import AsyncMock, MagicMock

from src.bot import bot as bot_module


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.set_my_commands = AsyncMock()
    bot.set_chat_menu_button = AsyncMock()
    return bot


class TestConfigureBotCommands:
    async def test_registers_private_chat_commands(self, monkeypatch):
        monkeypatch.setattr(bot_module.settings, "admin_user_id", 0)
        monkeypatch.setattr(bot_module.settings, "webapp_url", "")
        bot = _make_bot()

        await bot_module.configure_bot_commands(bot)

        bot.set_my_commands.assert_awaited_once()
        commands, kwargs = bot.set_my_commands.call_args.args, bot.set_my_commands.call_args.kwargs
        command_names = [c.command for c in commands[0]]
        assert command_names == ["start", "help", "nutrition", "statistics", "schedule", "my"]
        assert isinstance(kwargs["scope"], bot_module.BotCommandScopeAllPrivateChats)

    async def test_registers_admin_commands_with_full_list_plus_admin(self, monkeypatch):
        monkeypatch.setattr(bot_module.settings, "admin_user_id", 42)
        monkeypatch.setattr(bot_module.settings, "webapp_url", "")
        bot = _make_bot()

        await bot_module.configure_bot_commands(bot)

        # First call is the base private-chat list; second is per-admin.
        assert bot.set_my_commands.await_count == 2
        admin_call = bot.set_my_commands.call_args_list[1]
        admin_commands = [c.command for c in admin_call.args[0]]
        assert admin_commands == [
            "start", "help", "nutrition", "statistics", "schedule", "my", "admin",
        ]
        scope = admin_call.kwargs["scope"]
        assert isinstance(scope, bot_module.BotCommandScopeChat)
        assert scope.chat_id == 42

    async def test_skips_admin_without_crashing_on_failure(self, monkeypatch):
        monkeypatch.setattr(bot_module.settings, "admin_user_id", 42)
        monkeypatch.setattr(bot_module.settings, "webapp_url", "")
        bot = _make_bot()

        async def _fail(*args, **kwargs):
            if kwargs.get("scope") and isinstance(kwargs["scope"], bot_module.BotCommandScopeChat):
                raise RuntimeError("chat not found")

        bot.set_my_commands.side_effect = _fail

        # Should not raise despite the per-admin call failing.
        await bot_module.configure_bot_commands(bot)

    async def test_sets_global_menu_button_when_webapp_url_configured(self, monkeypatch):
        monkeypatch.setattr(bot_module.settings, "admin_user_id", 0)
        monkeypatch.setattr(bot_module.settings, "webapp_url", "https://example.com")
        bot = _make_bot()

        await bot_module.configure_bot_commands(bot)

        bot.set_chat_menu_button.assert_awaited_once()
        _, kwargs = bot.set_chat_menu_button.call_args
        assert "chat_id" not in kwargs
        assert kwargs["menu_button"].text == "📱 Щоденник"
        assert kwargs["menu_button"].web_app.url == "https://example.com/nutrition"

    async def test_skips_menu_button_when_webapp_url_missing(self, monkeypatch):
        monkeypatch.setattr(bot_module.settings, "admin_user_id", 0)
        monkeypatch.setattr(bot_module.settings, "webapp_url", "")
        bot = _make_bot()

        await bot_module.configure_bot_commands(bot)

        bot.set_chat_menu_button.assert_not_awaited()
