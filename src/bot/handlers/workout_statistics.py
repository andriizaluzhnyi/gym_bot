"""Workout statistics handler with Mini App integration (GYM-18)."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from src.config import get_settings

router = Router()
logger = logging.getLogger(__name__)
settings = get_settings()


@router.message(Command('statistics'))
async def cmd_statistics(message: Message) -> None:
    """
    Handle /statistics command.

    Opens the workout statistics Mini App (GYM-3).
    """
    webapp_url = settings.webapp_url

    if not webapp_url:
        await message.answer(
            '⚠️ Mini App URL не налаштовано.\n'
            'Додайте WEBAPP_URL до змінних оточення.'
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text='📊 Відкрити статистику',
                    web_app=WebAppInfo(url=f'{webapp_url}/statistics')
                )
            ]
        ]
    )

    await message.answer(
        '📊 *Статистика тренувань*\n\n'
        'Об\'єм, прогрес по вправах та активність.',
        reply_markup=keyboard
    )
