"""GYM-32: registers/deregisters a group chat when the bot is added to or
removed from it, via Telegram's `my_chat_member` update.

`GroupChat` rows this creates are what GYM-33's `/reminders` command edits
and GYM-34's scheduled jobs iterate — this ticket only wires up the
join/leave bookkeeping, nothing sends a reminder yet.
"""

import logging

from aiogram import F, Router
from aiogram.filters import JOIN_TRANSITION, LEAVE_TRANSITION, ChatMemberUpdatedFilter
from aiogram.types import ChatMemberUpdated

from src.database.repository import GroupChatRepository
from src.database.session import async_session_maker

router = Router()
logger = logging.getLogger(__name__)

_GROUP_CHAT_TYPES = {"group", "supergroup"}

_WELCOME_MESSAGE = (
    "Я нагадуватиму про харчування щодня о 20:00 і про заміри щопонеділка "
    "о 09:00. Налаштувати — /reminders"
)


@router.my_chat_member(
    ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION),
    F.chat.type.in_(_GROUP_CHAT_TYPES),
)
async def on_bot_added_to_group(event: ChatMemberUpdated) -> None:
    """The bot was added to a group/supergroup — upsert the `GroupChat`
    row (``is_active=True``) and greet with the default reminder
    schedule. Private chats never reach here — the `F.chat.type` filter
    (evaluated alongside `ChatMemberUpdatedFilter`, both on this same
    handler) restricts it to group/supergroup only.
    """
    async with async_session_maker() as session:
        await GroupChatRepository(session).upsert_active(
            chat_id=event.chat.id,
            title=event.chat.title,
            added_by_telegram_id=event.from_user.id,
        )
        await session.commit()

    try:
        await event.answer(_WELCOME_MESSAGE)
    except Exception as e:
        # Registration in the DB is what matters for GYM-33/34 — a failed
        # greeting (e.g. the bot was immediately muted) shouldn't undo it.
        logger.warning(f"Failed to send group welcome message: {e}")


@router.my_chat_member(
    ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION),
    F.chat.type.in_(_GROUP_CHAT_TYPES),
)
async def on_bot_removed_from_group(event: ChatMemberUpdated) -> None:
    """The bot was removed from (kicked or left) a group/supergroup —
    deactivate the `GroupChat` row. The row and its settings are kept, so
    they're restored automatically if the bot is re-added later (handled
    by ``upsert_active`` above finding the existing row instead of
    inserting a fresh one).
    """
    async with async_session_maker() as session:
        await GroupChatRepository(session).deactivate(event.chat.id)
        await session.commit()
