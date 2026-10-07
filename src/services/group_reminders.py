"""GYM-34: which group reminders are due, and sending them.

Split into a pure decision function (``due_reminders``, no I/O — every
branch is a plain comparison over a ``GroupChat`` snapshot and "now") and
a side-effecting service (``GroupReminderService``) that iterates active
groups, calls the pure function, and actually sends via a real ``Bot``.
Keeping the decision logic pure is what makes the tricky calendar edge
cases (midnight boundary, a late restart, day-of-month) testable without
mocking a clock and a bot at the same time.
"""

import logging
from datetime import datetime
from enum import Enum

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramNotFound
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import get_settings
from src.database.models import GroupChat
from src.database.repository import GroupChatRepository
from src.database.session import async_session_maker
from src.utils.datetime_utils import to_local_now
from src.utils.reminder_times import split_times, to_time

logger = logging.getLogger(__name__)
settings = get_settings()

_WEEKDAY_FULL_NAMES = [
    "Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя",
]


class ReminderKind(str, Enum):
    """One of the three reminder types a `GroupChat` can send (GYM-32's
    schema: `remind_*`/`*_time`/`last_*_sent_at` triplets), returned by
    `due_reminders()` for the scheduler job to act on.
    """

    NUTRITION = "nutrition"
    MEASUREMENTS = "measurements"
    PHOTOS = "photos"


def _latest_passed_slot(scheduled_times: str, now_local: datetime) -> datetime | None:
    """The latest of today's configured slots that is at/before
    ``now_local`` (as a full local ``datetime``), or ``None`` if none has
    been reached yet today.
    """
    passed = [
        slot for slot in split_times(scheduled_times)
        if to_time(slot) <= now_local.time()
    ]
    if not passed:
        return None
    return datetime.combine(now_local.date(), to_time(passed[-1]))


def _is_due(
    *, enabled: bool, scheduled_times: str, day_matches: bool,
    last_sent_at: datetime | None, now_local: datetime,
) -> bool:
    """One reminder type's "should this fire right now" rule: enabled,
    today is the right day, at least one of today's slots has been
    reached, and nothing has been sent since the latest such slot.

    Several slots per day are supported (``"08:00,13:00,20:00"``): each
    fires once, because ``last_sent_at`` (set right after a successful
    send by :meth:`GroupReminderService.send_due_reminders`) moves past
    it. A late restart still sends (AC: "бот перезапущений після 20:00 —
    надсилає з запізненням, але один раз") — if several slots were
    missed while the bot was down, they collapse into a single catch-up
    message rather than a burst.
    """
    if not enabled or not day_matches:
        return False
    slot = _latest_passed_slot(scheduled_times, now_local)
    if slot is None:
        return False
    return last_sent_at is None or last_sent_at < slot


def due_reminders(group: GroupChat, now_local: datetime) -> list[ReminderKind]:
    """Which reminder types are due to be sent to `group` right this
    moment (`now_local` — a local wall-clock ``datetime``, see
    :func:`src.utils.datetime_utils.to_local_now`).

    - Nutrition: every day, at each of ``nutrition_time``'s slots.
    - Measurements: only on ``measurements_weekday`` (0 = Monday, matching
      ``datetime.weekday()``), at each of ``measurements_time``'s slots.
    - Photos: only on ``photos_day_of_month`` (an exact day-of-month
      match — the field is capped at 1-28 in the UI specifically so every
      month has that day; the 29th-31st of a longer month never matches
      a lower ``photos_day_of_month``, they're just not that day), at
      each of ``photos_time``'s slots.

    Pure — no DB/network access, so every calendar edge case is a plain
    unit test against a constructed ``GroupChat`` and an arbitrary
    ``now_local``.
    """
    due: list[ReminderKind] = []

    if _is_due(
        enabled=group.remind_nutrition,
        scheduled_times=group.nutrition_time,
        day_matches=True,
        last_sent_at=group.last_nutrition_sent_at,
        now_local=now_local,
    ):
        due.append(ReminderKind.NUTRITION)

    if _is_due(
        enabled=group.remind_measurements,
        scheduled_times=group.measurements_time,
        day_matches=now_local.weekday() == group.measurements_weekday,
        last_sent_at=group.last_measurements_sent_at,
        now_local=now_local,
    ):
        due.append(ReminderKind.MEASUREMENTS)

    if _is_due(
        enabled=group.remind_photos,
        scheduled_times=group.photos_time,
        day_matches=now_local.day == group.photos_day_of_month,
        last_sent_at=group.last_photos_sent_at,
        now_local=now_local,
    ):
        due.append(ReminderKind.PHOTOS)

    return due


def _deeplink_keyboard(
    label: str, section: str, bot_username: str | None
) -> InlineKeyboardMarkup | None:
    """A single `url` button (not `web_app` — those don't render inside a
    group chat) linking to ``https://t.me/<bot>?start=<section>``; the
    private-chat `/start <section>` handler (``src/bot/handlers/start.py``)
    replies to *that* with a real `web_app` button, since deep-linking
    always opens a private chat. Returns ``None`` (no button — text-only
    message) if the bot's username hasn't been cached yet (see
    ``src.webapp.server.get_bot_username``) — a broken link is worse than
    no link.
    """
    if not bot_username:
        return None
    url = f"https://t.me/{bot_username}?start={section}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, url=url)]])


def _build_reminder_message(
    kind: ReminderKind, group: GroupChat, bot_username: str | None,
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Text + optional keyboard for one reminder kind, per GYM-34's AC."""
    if kind is ReminderKind.NUTRITION:
        text = (
            "🍽 Час підбити харчування за сьогодні — залогуйте прийоми їжі "
            "та воду"
        )
        return text, _deeplink_keyboard("🍎 Відкрити щоденник", "nutrition", bot_username)

    if kind is ReminderKind.MEASUREMENTS:
        day_name = _WEEKDAY_FULL_NAMES[group.measurements_weekday]
        text = f"📏 {day_name} — день замірів. Оновіть вагу в профілі"
        return text, _deeplink_keyboard("👤 Профіль", "profile", bot_username)

    if kind is ReminderKind.PHOTOS:
        # No button — the bot doesn't collect photos (see plan's
        # "Відкриті питання"), so there's nowhere useful to link to.
        text = (
            "📸 Час для фото прогресу\n"
            "Зробіть фото в тих самих умовах, що й минулого разу"
        )
        return text, None

    raise ValueError(f"Unknown reminder kind: {kind!r}")  # pragma: no cover


class GroupReminderService:
    """Sends due reminders (GYM-34) — the side-effecting half of
    :func:`due_reminders`'s pure decision logic. Instantiated fresh per
    scheduler tick (``setup_scheduler``), same convention as
    ``NotificationService``.
    """

    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_due_reminders(self) -> int:
        """For every active group, work out which reminder types are due
        right now and send them. Returns how many messages were sent.

        A ``TelegramForbiddenError``/``TelegramNotFound`` (the bot was
        removed from the group without a `my_chat_member` update ever
        reaching us — happens if the group itself was deleted, or Telegram
        dropped the update) deactivates that group, mirroring
        ``on_bot_removed_from_group``. Any other send failure is logged
        and ``last_*_sent_at`` is left untouched, so the next tick (1 min
        later) retries it.
        """
        from src.webapp.server import get_bot_username

        bot_username = get_bot_username()
        sent_count = 0

        async with async_session_maker() as session:
            repo = GroupChatRepository(session)
            groups = await repo.get_active()

            for group in groups:
                now_local = to_local_now(settings.timezone)
                for kind in due_reminders(group, now_local):
                    text, keyboard = _build_reminder_message(kind, group, bot_username)
                    try:
                        await self.bot.send_message(
                            group.chat_id, text,
                            parse_mode="Markdown", reply_markup=keyboard,
                        )
                    except (TelegramForbiddenError, TelegramNotFound) as e:
                        logger.warning(
                            f"Group {group.chat_id} unreachable, deactivating: {e}"
                        )
                        await repo.deactivate(group.chat_id)
                        break  # this group's other due reminders would fail too
                    except Exception as e:
                        logger.warning(
                            f"Failed to send {kind.value} reminder to "
                            f"{group.chat_id}: {e}"
                        )
                        continue

                    await repo.mark_sent(group.chat_id, kind.value, now_local)
                    logger.info(
                        f"Sent {kind.value} reminder to group {group.chat_id} "
                        f"at {now_local:%Y-%m-%d %H:%M} ({settings.timezone})"
                    )
                    sent_count += 1

            await session.commit()

        return sent_count
