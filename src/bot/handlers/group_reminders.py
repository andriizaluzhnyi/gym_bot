"""GYM-32/33: group-chat reminder registration and the `/reminders`
settings panel.

GYM-32 registers/deregisters a `GroupChat` row when the bot is added to
or removed from a group, via Telegram's `my_chat_member` update. GYM-33
adds the `/reminders` command and its inline settings panel, editing that
same row. Neither ticket sends an actual reminder yet — that's GYM-34,
which reads `GroupChat.remind_*`/`*_time`/`last_*_sent_on` written here.
"""

import logging

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.filters import JOIN_TRANSITION, LEAVE_TRANSITION, ChatMemberUpdatedFilter, Command
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from src.bot.keyboards import (
    GROUP_REMINDER_DAY_OF_MONTH_CHOICES,
    GROUP_REMINDER_TIME_CHOICES,
    get_group_reminders_panel_keyboard,
    get_group_reminders_time_keyboard,
)
from src.database.repository import GroupChatRepository
from src.database.session import async_session_maker

router = Router()
logger = logging.getLogger(__name__)

_GROUP_CHAT_TYPES = {"group", "supergroup"}
_GROUP_ADMIN_STATUSES = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}

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


async def _is_group_admin(bot, chat_id: int, user_id: int) -> bool:
    """True if `user_id` is that group's creator/administrator — GYM-33's
    AC restricts *changing* settings to them (viewing the panel, i.e.
    running ``/reminders`` itself, is open to everyone in the group).
    """
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception as e:
        logger.warning(f"Failed to check group admin status: {e}")
        return False
    return member.status in _GROUP_ADMIN_STATUSES


@router.message(Command("reminders"))
async def cmd_reminders(message: Message) -> None:
    """`/reminders` — show the settings panel (GYM-33). Group/supergroup
    only; in a private chat there's nothing to configure, so this just
    points the user at adding the bot to a group instead.
    """
    if message.chat.type not in _GROUP_CHAT_TYPES:
        await message.answer("Додайте мене в групу, щоб налаштувати нагадування.")
        return

    async with async_session_maker() as session:
        group = await GroupChatRepository(session).get_by_chat_id(message.chat.id)

    if group is None:
        # Shouldn't normally happen — on_bot_added_to_group registers a
        # row the moment the bot joins — but a missed/lost my_chat_member
        # update could leave a group without one.
        await message.answer(
            "Ще не бачу цю групу зареєстрованою. Спробуйте видалити й "
            "додати мене в групу ще раз."
        )
        return

    await message.answer(
        "⏰ Нагадування в цій групі:",
        reply_markup=get_group_reminders_panel_keyboard(group),
    )


@router.callback_query(F.data.startswith("grem:"))
async def process_reminders_callback(callback: CallbackQuery) -> None:
    """Handle every `grem:*` button (GYM-33) — toggle a reminder type,
    open its time-choice submenu, apply a chosen time/weekday/
    day-of-month, or go back to the main panel. Every branch that changes
    a setting re-renders the panel keyboard in place
    (``edit_reply_markup``) rather than sending a new message, per AC.
    """
    if (
        callback.data is None
        or not isinstance(callback.message, Message)
        or callback.from_user is None
    ):
        await callback.answer()
        return

    chat = callback.message.chat
    if chat.type not in _GROUP_CHAT_TYPES:
        await callback.answer()
        return

    if not await _is_group_admin(callback.bot, chat.id, callback.from_user.id):
        await callback.answer("Лише адміни групи", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer()
        return
    action = parts[1]

    try:
        async with async_session_maker() as session:
            repo = GroupChatRepository(session)
            group = await repo.get_by_chat_id(chat.id)
            if group is None:
                await callback.answer()
                return

            if action == "time":
                reminder_type = parts[2]
                await callback.message.edit_reply_markup(
                    reply_markup=get_group_reminders_time_keyboard(reminder_type)
                )
                await callback.answer()
                return

            if action == "toggle":
                reminder_type = parts[2]
                if reminder_type == "nutrition":
                    await repo.update_settings(
                        chat.id, remind_nutrition=not group.remind_nutrition
                    )
                elif reminder_type == "measurements":
                    await repo.update_settings(
                        chat.id, remind_measurements=not group.remind_measurements
                    )
                elif reminder_type == "photos":
                    await repo.update_settings(
                        chat.id, remind_photos=not group.remind_photos
                    )
                else:
                    await callback.answer()
                    return

            elif action == "settime":
                # "HH:MM" itself contains a ":", so parts[3] alone would
                # only be the "HH" half — rejoin everything after the
                # reminder type to recover the full time string.
                reminder_type, time_str = parts[2], ":".join(parts[3:])
                if time_str not in GROUP_REMINDER_TIME_CHOICES:
                    await callback.answer("Невірний час", show_alert=True)
                    return
                if reminder_type == "nutrition":
                    await repo.update_settings(chat.id, nutrition_time=time_str)
                elif reminder_type == "measurements":
                    await repo.update_settings(chat.id, measurements_time=time_str)
                elif reminder_type == "photos":
                    await repo.update_settings(chat.id, photos_time=time_str)
                else:
                    await callback.answer()
                    return

            elif action == "setweekday":
                weekday = int(parts[2])
                if weekday not in range(7):
                    await callback.answer("Невірний день тижня", show_alert=True)
                    return
                await repo.update_settings(chat.id, measurements_weekday=weekday)

            elif action == "setday":
                day = int(parts[2])
                if day not in GROUP_REMINDER_DAY_OF_MONTH_CHOICES:
                    await callback.answer("Невірне число", show_alert=True)
                    return
                await repo.update_settings(chat.id, photos_day_of_month=day)

            elif action != "back":
                await callback.answer()
                return

            await session.commit()
            group = await repo.get_by_chat_id(chat.id)
    except (IndexError, KeyError, ValueError) as e:
        # Malformed/stale callback_data (shouldn't happen from our own
        # buttons, but callback_data can outlive a bot redeploy) — fail
        # closed rather than crash the handler.
        logger.warning(f"Malformed /reminders callback_data {callback.data!r}: {e}")
        await callback.answer()
        return

    assert group is not None  # re-fetched right after a successful write
    await callback.message.edit_reply_markup(
        reply_markup=get_group_reminders_panel_keyboard(group)
    )
    await callback.answer()
