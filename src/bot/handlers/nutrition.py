"""Nutrition tracking handler with Mini App integration."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

from src.config import get_settings

router = Router()
logger = logging.getLogger(__name__)
settings = get_settings()


@router.message(Command('nutrition'))
async def cmd_nutrition(message: Message) -> None:
    """
    Handle /nutrition command.

    Opens the nutrition tracking Mini App.
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
                    text='🍎 Відкрити трекер харчування',
                    web_app=WebAppInfo(url=f'{webapp_url}/nutrition')
                )
            ]
        ]
    )

    await message.answer(
        '📊 *Трекер харчування*\n\n'
        'Відстежуйте калорії, БЖУ та воду.',
        reply_markup=keyboard
    )
