"""Tests for /start, /help and contact-sharing handlers
(src/bot/handlers/start.py).
"""

import uuid

import pytest

from src.bot.handlers import start
from src.database.models import Base
from src.database.repository import UserRepository
from src.database.session import async_session_maker, engine
from tests.bot_mocks import make_contact, make_message, make_telegram_user


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


def _unique_telegram_id() -> int:
    return uuid.uuid4().int % (2**31)


class TestCmdStart:
    async def test_no_from_user_does_nothing(self):
        message = make_message(from_user=None)
        await start.cmd_start(message)
        message.answer.assert_not_awaited()

    async def test_creates_new_user_and_sends_main_menu(self, monkeypatch):
        monkeypatch.setattr(start.settings, "admin_user_id", 0)
        telegram_id = _unique_telegram_id()
        user = make_telegram_user(user_id=telegram_id, first_name="Andrii", username="andrii")
        message = make_message(from_user=user)

        await start.cmd_start(message)

        message.answer.assert_awaited_once()
        (text,), kwargs = message.answer.call_args
        assert "Andrii" in text
        assert kwargs["parse_mode"] == "Markdown"

        async with async_session_maker() as session:
            db_user = await UserRepository(session).get_by_telegram_id(telegram_id)
            assert db_user is not None
            assert db_user.is_admin is False

    async def test_admin_user_id_gets_admin_menu_and_flag(self, monkeypatch):
        telegram_id = _unique_telegram_id()
        monkeypatch.setattr(start.settings, "admin_user_id", telegram_id)
        user = make_telegram_user(user_id=telegram_id, first_name="Boss")
        message = make_message(from_user=user)

        await start.cmd_start(message)

        async with async_session_maker() as session:
            db_user = await UserRepository(session).get_by_telegram_id(telegram_id)
            assert db_user.is_admin is True

    async def test_sets_chat_menu_button_when_webapp_url_configured(self, monkeypatch):
        monkeypatch.setattr(start.settings, "admin_user_id", 0)
        monkeypatch.setattr(start.settings, "webapp_url", "https://example.com")
        message = make_message(from_user=make_telegram_user(user_id=_unique_telegram_id()))

        await start.cmd_start(message)

        message.bot.set_chat_menu_button.assert_awaited_once()
        _, kwargs = message.bot.set_chat_menu_button.call_args
        assert kwargs["menu_button"].web_app.url == "https://example.com/nutrition"

    async def test_skips_chat_menu_button_when_webapp_url_missing(self, monkeypatch):
        monkeypatch.setattr(start.settings, "admin_user_id", 0)
        monkeypatch.setattr(start.settings, "webapp_url", "")
        message = make_message(from_user=make_telegram_user(user_id=_unique_telegram_id()))

        await start.cmd_start(message)

        message.bot.set_chat_menu_button.assert_not_awaited()


class TestCmdHelp:
    async def test_sends_help_text(self):
        message = make_message(text="/help")
        await start.cmd_help(message)

        message.answer.assert_awaited_once()
        (text,), kwargs = message.answer.call_args
        assert "Інструкція" in text
        assert kwargs["parse_mode"] == "Markdown"


class TestContactHandler:
    async def test_no_contact_does_nothing(self):
        message = make_message(contact=None)
        await start.contact_handler(message)
        message.answer.assert_not_awaited()

    async def test_no_from_user_does_nothing(self):
        message = make_message(contact=make_contact(), from_user=None)
        await start.contact_handler(message)
        message.answer.assert_not_awaited()

    async def test_rejects_contact_belonging_to_someone_else(self):
        telegram_id = _unique_telegram_id()
        user = make_telegram_user(user_id=telegram_id)
        contact = make_contact(user_id=telegram_id + 1)
        message = make_message(from_user=user, contact=contact)

        await start.contact_handler(message)

        message.answer.assert_awaited_once_with(
            "❌ Будь ласка, поділіться своїм контактом"
        )

    async def test_updates_phone_for_existing_user(self):
        telegram_id = _unique_telegram_id()
        async with async_session_maker() as session:
            await UserRepository(session).get_or_create(
                telegram_id=telegram_id, first_name="Andrii"
            )
            await session.commit()

        user = make_telegram_user(user_id=telegram_id)
        contact = make_contact(phone_number="+380501112233", user_id=telegram_id)
        message = make_message(from_user=user, contact=contact)

        await start.contact_handler(message)

        message.answer.assert_awaited_once()
        (text,), _ = message.answer.call_args
        assert "+380501112233" in text

        async with async_session_maker() as session:
            db_user = await UserRepository(session).get_by_telegram_id(telegram_id)
            assert db_user.phone == "+380501112233"

    async def test_unknown_user_gets_error_message(self):
        telegram_id = _unique_telegram_id()
        user = make_telegram_user(user_id=telegram_id)
        contact = make_contact(user_id=telegram_id)
        message = make_message(from_user=user, contact=contact)

        await start.contact_handler(message)

        message.answer.assert_awaited_once_with("❌ Помилка оновлення профілю")
