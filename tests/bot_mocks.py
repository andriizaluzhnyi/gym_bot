"""Shared aiogram object mocks for bot handler tests.

Not a test module itself (no ``test_`` prefix, not collected by pytest) —
just factories for the ``Message``/``CallbackQuery``/``User`` objects
handlers receive, so each handler test file doesn't reinvent them.

Uses ``MagicMock(spec=...)`` rather than constructing real aiogram/pydantic
objects: ``spec=`` makes ``isinstance()`` checks against the real class
succeed (handlers rely on this, e.g. ``isinstance(callback.message,
Message)``), while letting tests set only the attributes they need.
Async methods (``answer``, ``edit_text``, ...) are not auto-mocked as
coroutines by ``spec=`` alone, so each factory sets them explicitly.
"""

from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, ChatMemberUpdated, Contact, Message, User

# Distinguishes "caller didn't pass this" (use the default) from an
# explicit `None` (e.g. simulating `message.from_user is None`), which a
# plain `None` default can't do.
_UNSET = object()


def make_telegram_user(
    *, user_id: int = 1, first_name: str = "Test", last_name: str | None = None,
    username: str | None = None,
) -> User:
    user = MagicMock(spec=User)
    user.id = user_id
    user.first_name = first_name
    user.last_name = last_name
    user.username = username
    return user


def make_chat(
    *, chat_id: int = 1, chat_type: str = "private", title: str | None = None
) -> Chat:
    chat = MagicMock(spec=Chat)
    chat.id = chat_id
    chat.type = chat_type
    # `spec=Chat` only exposes attributes present in `dir(Chat)` — pydantic
    # fields like `title` aren't class attributes, so they must be set
    # explicitly here or accessing `.title` raises AttributeError (GYM-32).
    chat.title = title
    return chat


def make_message(
    *, text: str | None = None, from_user=_UNSET,
    chat=_UNSET, contact: Contact | None = None,
    bot=_UNSET,
) -> Message:
    message = MagicMock(spec=Message)
    message.text = text
    message.from_user = make_telegram_user() if from_user is _UNSET else from_user
    message.chat = make_chat() if chat is _UNSET else chat
    message.contact = contact
    message.bot = MagicMock() if bot is _UNSET else bot
    if message.bot is not None:
        message.bot.set_chat_menu_button = AsyncMock()
    message.answer = AsyncMock()
    message.edit_text = AsyncMock()
    message.edit_reply_markup = AsyncMock()
    message.answer_photo = AsyncMock()
    return message


def make_contact(
    *, phone_number: str = "+380501234567", user_id: int | None = None
) -> Contact:
    contact = MagicMock(spec=Contact)
    contact.phone_number = phone_number
    contact.user_id = user_id
    return contact


def make_fsm_context(*, chat_id: int = 1, user_id: int = 1) -> FSMContext:
    """A real ``FSMContext`` backed by ``MemoryStorage``.

    Handlers call several distinct FSM methods (``set_state``,
    ``update_data``, ``get_data``, ``clear``, ...); exercising the real thing
    against in-memory storage is simpler and more faithful than mocking each
    method, and it's fully isolated per test (fresh storage every call).
    """
    return FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=1, chat_id=chat_id, user_id=user_id),
    )


def make_callback(
    *, data: str | None = None, from_user=_UNSET, message=_UNSET,
) -> CallbackQuery:
    callback = MagicMock(spec=CallbackQuery)
    callback.data = data
    callback.from_user = make_telegram_user() if from_user is _UNSET else from_user
    callback.message = make_message() if message is _UNSET else message
    callback.answer = AsyncMock()
    return callback


def _make_chat_member(*, status: str):
    """A bare stand-in for aiogram's `ChatMember*` union — GYM-32's
    `ChatMemberUpdatedFilter` (via `JOIN_TRANSITION`/`LEAVE_TRANSITION`)
    only ever reads `.status` off these (``getattr(member, "status",
    None)``, see aiogram.filters.chat_member_updated), so a bare
    ``MagicMock`` with that one attribute set is enough — no need for a
    real ``ChatMemberMember``/``ChatMemberLeft`` instance.
    """
    member = MagicMock()
    member.status = status
    return member


def make_chat_member_updated(
    *, chat=_UNSET, from_user=_UNSET, old_status: str = "left",
    new_status: str = "member",
) -> ChatMemberUpdated:
    """A `my_chat_member` update (GYM-32). Defaults to a "bot joined a
    group" transition (``left`` -> ``member``, i.e. `JOIN_TRANSITION`) —
    pass ``old_status="member", new_status="left"`` (or ``"kicked"``) for
    a "bot removed" transition (`LEAVE_TRANSITION`). ``chat`` defaults to
    a group chat (not private — GYM-32's handlers ignore private chats).
    """
    event = MagicMock(spec=ChatMemberUpdated)
    event.chat = make_chat(chat_type="group") if chat is _UNSET else chat
    event.from_user = make_telegram_user() if from_user is _UNSET else from_user
    event.old_chat_member = _make_chat_member(status=old_status)
    event.new_chat_member = _make_chat_member(status=new_status)
    event.answer = AsyncMock()
    return event
