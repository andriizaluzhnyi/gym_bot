"""GYM-32/33: group-chat reminder registration and the `/reminders`
settings panel — where a trainer (the bot admin) or a group admin sets
any number of reminders per day, at any time (preset chips, or
"✏️ Свій час" for free-form input).

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
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ChatMemberUpdated, ForceReply, Message

from src.bot.keyboards import (
    GROUP_REMINDER_DAY_OF_MONTH_CHOICES,
    GROUP_REMINDER_LABELS,
    GROUP_REMINDER_TIME_FIELDS,
    get_group_reminder_times,
    get_group_reminders_panel_keyboard,
    get_group_reminders_time_keyboard,
)
from src.config import get_settings
from src.database.repository import GroupChatRepository
from src.database.session import async_session_maker
from src.utils.datetime_utils import to_local_now
from src.utils.reminder_times import (
    MAX_REMINDER_TIMES_PER_DAY,
    join_times,
    normalize_time,
    parse_time_input,
)

router = Router()
logger = logging.getLogger(__name__)
settings = get_settings()


class GroupReminderStates(StatesGroup):
    """"✏️ Свій час" — waiting for the trainer to reply with time(s)."""

    waiting_times = State()


_GROUP_CHAT_TYPES = {"group", "supergroup"}
_GROUP_ADMIN_STATUSES = {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}

_WELCOME_MESSAGE = (
    "Я нагадуватиму про харчування щодня о 20:00 і про заміри щопонеділка "
    "о 09:00. Налаштувати (будь-який час і кілька нагадувань на день) — "
    "/reminders"
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


def _is_trainer(user_id: int) -> bool:
    """The bot's own admin(s) (``ADMIN_USER_ID`` — the trainer) may manage
    reminders in any group the bot is in, even without being that group's
    Telegram admin.
    """
    return user_id in settings.admin_user_ids


async def _can_manage_reminders(bot, chat_id: int, user_id: int) -> bool:
    if _is_trainer(user_id):
        return True
    return await _is_group_admin(bot, chat_id, user_id)


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


_NO_PERMISSION_ALERT = "Лише тренер або адміни групи"
_TIME_FIELD_BY_TYPE = GROUP_REMINDER_TIME_FIELDS


async def _skip_past_slots(repo: GroupChatRepository, chat_id: int, reminder_type: str) -> None:
    """A schedule change only affects slots from now on — see
    ``GroupChatRepository.skip_past_slots``."""
    await repo.skip_past_slots(chat_id, reminder_type, to_local_now(settings.timezone))


@router.callback_query(F.data.startswith("grem:custom:"))
async def process_reminders_custom_time(callback: CallbackQuery, state: FSMContext) -> None:
    """"✏️ Свій час" — ask the trainer to reply with any time(s), e.g.
    ``08:15, 13:00, 21:45``. A `ForceReply` is used so the reply reaches
    the bot even with group privacy mode on (bots always see replies to
    their own messages); the FSM state is per user-in-chat, so only the
    person who pressed the button is being listened to.
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

    if not await _can_manage_reminders(callback.bot, chat.id, callback.from_user.id):
        await callback.answer(_NO_PERMISSION_ALERT, show_alert=True)
        return

    reminder_type = callback.data.split(":", 2)[2]
    if reminder_type not in _TIME_FIELD_BY_TYPE:
        await callback.answer()
        return

    await state.set_state(GroupReminderStates.waiting_times)
    await state.update_data(reminder_type=reminder_type)

    label = GROUP_REMINDER_LABELS[reminder_type]
    # `selective` ForceReply targets only @mentioned users — mention the
    # trainer so the reply box pops up for them, not the whole group.
    mention = callback.from_user.mention_html()
    await callback.message.answer(
        f"{mention}, {label}: надішліть час у відповідь на це повідомлення — один або "
        f"кілька через кому/пробіл, у форматі ГГ:ХХ.\n"
        f"Напр.: 08:15, 13:00, 21:45\n"
        f"Ці часи додадуться до поточних (до {MAX_REMINDER_TIMES_PER_DAY} на день). "
        f"Щоб скасувати — надішліть «-».",
        parse_mode="HTML",
        reply_markup=ForceReply(selective=True, input_field_placeholder="08:15, 13:00"),
    )
    await callback.answer()


@router.message(GroupReminderStates.waiting_times)
async def process_reminders_times_input(message: Message, state: FSMContext) -> None:
    """The reply to "✏️ Свій час": parse, merge into the reminder's
    slots, and show the updated panel. Invalid input keeps the state so
    the trainer can just try again; "-" (or /cancel) cancels.
    """
    if message.from_user is None or message.chat.type not in _GROUP_CHAT_TYPES:
        await state.clear()
        return

    text = (message.text or "").strip()
    if text in {"-", "/cancel", "скасувати", "Скасувати"}:
        await state.clear()
        await message.answer("Скасовано.")
        return

    data = await state.get_data()
    reminder_type = data.get("reminder_type")
    if reminder_type not in _TIME_FIELD_BY_TYPE:
        await state.clear()
        return

    if not await _can_manage_reminders(message.bot, message.chat.id, message.from_user.id):
        await state.clear()
        await message.answer(_NO_PERMISSION_ALERT)
        return

    try:
        new_times = parse_time_input(text)
    except ValueError:
        await message.answer(
            "Не розпізнав час. Формат ГГ:ХХ, кілька — через кому, напр. "
            "08:15, 13:00, 21:45. Спробуйте ще раз або надішліть «-»."
        )
        return

    async with async_session_maker() as session:
        repo = GroupChatRepository(session)
        group = await repo.get_by_chat_id(message.chat.id)
        if group is None:
            await state.clear()
            return

        merged = sorted(set(get_group_reminder_times(reminder_type, group)) | set(new_times))
        if len(merged) > MAX_REMINDER_TIMES_PER_DAY:
            await message.answer(
                f"Забагато нагадувань: максимум {MAX_REMINDER_TIMES_PER_DAY} на день. "
                f"Видаліть зайві в /reminders або надішліть менше часу."
            )
            return

        await repo.set_times(message.chat.id, reminder_type, join_times(merged))
        await _skip_past_slots(repo, message.chat.id, reminder_type)
        await session.commit()
        group = await repo.get_by_chat_id(message.chat.id)

    await state.clear()
    assert group is not None
    label = GROUP_REMINDER_LABELS[reminder_type]
    await message.answer(
        f"✅ {label}: {', '.join(merged)}",
        reply_markup=get_group_reminders_panel_keyboard(group),
    )


@router.callback_query(F.data.startswith("grem:"))
async def process_reminders_callback(callback: CallbackQuery) -> None:
    """Handle every other `grem:*` button (GYM-33) — toggle a reminder
    type, open its time submenu, add/remove a time slot, apply a
    weekday/day-of-month, or go back to the main panel. Every branch that
    changes a setting re-renders the keyboard in place
    (``edit_reply_markup``) rather than sending a new message, per AC.
    Time edits stay in the submenu so several can be made in a row.
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

    if not await _can_manage_reminders(callback.bot, chat.id, callback.from_user.id):
        await callback.answer(_NO_PERMISSION_ALERT, show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer()
        return
    action = parts[1]
    # Which submenu to re-render after a change (None = the main panel).
    submenu_type: str | None = None

    try:
        async with async_session_maker() as session:
            repo = GroupChatRepository(session)
            group = await repo.get_by_chat_id(chat.id)
            if group is None:
                await callback.answer()
                return

            if action == "time":
                reminder_type = parts[2]
                if reminder_type not in _TIME_FIELD_BY_TYPE:
                    await callback.answer()
                    return
                await callback.message.edit_reply_markup(
                    reply_markup=get_group_reminders_time_keyboard(reminder_type, group)
                )
                await callback.answer()
                return

            if action == "toggle":
                reminder_type = parts[2]
                if reminder_type == "nutrition":
                    enabled = not group.remind_nutrition
                    await repo.update_settings(chat.id, remind_nutrition=enabled)
                elif reminder_type == "measurements":
                    enabled = not group.remind_measurements
                    await repo.update_settings(chat.id, remind_measurements=enabled)
                elif reminder_type == "photos":
                    enabled = not group.remind_photos
                    await repo.update_settings(chat.id, remind_photos=enabled)
                else:
                    await callback.answer()
                    return
                if enabled:
                    await _skip_past_slots(repo, chat.id, reminder_type)

            elif action in {"settime", "addtime", "deltime"}:
                # "HH:MM" itself contains a ":", so parts[3] alone would
                # only be the "HH" half — rejoin everything after the
                # reminder type to recover the full time string.
                reminder_type = parts[2]
                if reminder_type not in _TIME_FIELD_BY_TYPE:
                    await callback.answer()
                    return
                try:
                    time_str = normalize_time(":".join(parts[3:]))
                except ValueError:
                    await callback.answer("Невірний час", show_alert=True)
                    return

                current = get_group_reminder_times(reminder_type, group)
                if action == "settime":
                    # Legacy single-time button (panels sent before
                    # multi-time support): replace the whole list.
                    new_times = [time_str]
                elif action == "addtime":
                    if len(current) >= MAX_REMINDER_TIMES_PER_DAY and time_str not in current:
                        await callback.answer(
                            f"Максимум {MAX_REMINDER_TIMES_PER_DAY} нагадувань на день",
                            show_alert=True,
                        )
                        return
                    new_times = sorted(set(current) | {time_str})
                    submenu_type = reminder_type
                else:  # deltime
                    if time_str in current and len(current) <= 1:
                        await callback.answer(
                            "Має лишитися хоча б один час — або вимкніть "
                            "це нагадування в головному меню",
                            show_alert=True,
                        )
                        return
                    new_times = [t for t in current if t != time_str]
                    submenu_type = reminder_type

                await repo.set_times(chat.id, reminder_type, join_times(new_times))
                await _skip_past_slots(repo, chat.id, reminder_type)

            elif action == "setweekday":
                weekday = int(parts[2])
                if weekday not in range(7):
                    await callback.answer("Невірний день тижня", show_alert=True)
                    return
                await repo.update_settings(chat.id, measurements_weekday=weekday)
                await _skip_past_slots(repo, chat.id, "measurements")
                submenu_type = "measurements"

            elif action == "setday":
                day = int(parts[2])
                if day not in GROUP_REMINDER_DAY_OF_MONTH_CHOICES:
                    await callback.answer("Невірне число", show_alert=True)
                    return
                await repo.update_settings(chat.id, photos_day_of_month=day)
                await _skip_past_slots(repo, chat.id, "photos")
                submenu_type = "photos"

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
    if submenu_type is not None:
        keyboard = get_group_reminders_time_keyboard(submenu_type, group)
    else:
        keyboard = get_group_reminders_panel_keyboard(group)
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()
