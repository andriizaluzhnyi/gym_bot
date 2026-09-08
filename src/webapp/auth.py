"""Shared authentication helpers for Telegram Mini App API endpoints.

Every ``/api/*`` handler needs to validate the Telegram WebApp ``initData``
sent in the ``Authorization`` header. Historically each handler duplicated
that ~8-line check inline (see ``src/webapp/server.py``); this module gives
new endpoints a single decorator instead. Existing endpoints are not
required to migrate.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from urllib.parse import parse_qsl

from aiohttp import web

from src.config import get_settings

logger = logging.getLogger(__name__)

Handler = Callable[[web.Request], Awaitable[web.Response]]

#: Typed key for the decoded Telegram user dict stashed on the request by
#: :func:`webapp_auth` — a plain string key triggers aiohttp's
#: ``NotAppKeyWarning`` (see https://docs.aiohttp.org/en/stable/web_advanced.html#request-s-storage).
TELEGRAM_USER_KEY: web.RequestKey[dict] = web.RequestKey("telegram_user")


def validate_telegram_webapp_data(init_data: str) -> dict | None:
    """Validate Telegram WebApp initData and return the embedded user data.

    Args:
        init_data: The initData string from Telegram WebApp.

    Returns:
        Dictionary with user data if valid, None otherwise.
    """
    if not init_data:
        return None

    settings = get_settings()

    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop('hash', None)

        if not received_hash:
            return None

        data_check_string = '\n'.join(
            f'{k}={v}' for k, v in sorted(parsed.items())
        )

        secret_key = hmac.new(
            b'WebAppData',
            settings.telegram_bot_token.encode(),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if calculated_hash != received_hash:
            return None

        user_data = parsed.get('user')
        if user_data:
            return json.loads(user_data)

        return None
    except Exception as e:
        logger.error(f'Error validating Telegram WebApp data: {e}')
        return None


def webapp_auth(handler: Handler) -> Handler:
    """Require valid Telegram WebApp ``initData`` before calling ``handler``.

    Validates the ``Authorization`` header via
    :func:`validate_telegram_webapp_data`. On failure, responds with ``401``
    without calling the wrapped handler. On success, stores the decoded
    Telegram user dict on ``request[TELEGRAM_USER_KEY]`` and calls the
    handler.

    Use this for new ``/api/*`` endpoints instead of repeating the validation
    boilerplate; existing endpoints keep working as-is.
    """

    @wraps(handler)
    async def wrapper(request: web.Request) -> web.Response:
        init_data = request.headers.get('Authorization', '')
        telegram_user = validate_telegram_webapp_data(init_data)

        if not telegram_user:
            return web.json_response({'error': 'Unauthorized'}, status=401)

        request[TELEGRAM_USER_KEY] = telegram_user
        return await handler(request)

    return wrapper
