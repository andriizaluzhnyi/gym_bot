"""Tests for the shared Telegram WebApp auth helpers (src/webapp/auth.py)."""

import hashlib
import hmac
import json
from urllib.parse import urlencode

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.config import get_settings
from src.webapp.auth import TELEGRAM_USER_KEY, validate_telegram_webapp_data, webapp_auth

BOT_TOKEN = get_settings().telegram_bot_token


def build_init_data(user: dict, *, token: str = BOT_TOKEN) -> str:
    """Build a signed Telegram WebApp initData string for tests."""
    params = {
        "auth_date": "1700000000",
        "query_id": "AAA-test-query-id",
        "user": json.dumps(user, separators=(",", ":")),
    }

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(params.items())
    )
    secret_key = hmac.new(
        b"WebAppData", token.encode(), hashlib.sha256
    ).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    params["hash"] = calculated_hash
    return urlencode(params)


class TestValidateTelegramWebappData:
    def test_valid_init_data_returns_user(self):
        user = {"id": 123, "first_name": "Andrii", "username": "zaluzhnyi"}
        init_data = build_init_data(user)

        result = validate_telegram_webapp_data(init_data)

        assert result == user

    def test_empty_init_data_returns_none(self):
        assert validate_telegram_webapp_data("") is None

    def test_tampered_hash_returns_none(self):
        user = {"id": 123, "first_name": "Andrii"}
        init_data = build_init_data(user, token="a-different-bot-token")

        assert validate_telegram_webapp_data(init_data) is None

    def test_missing_hash_returns_none(self):
        init_data = urlencode({"user": json.dumps({"id": 1})})

        assert validate_telegram_webapp_data(init_data) is None

    def test_garbage_init_data_returns_none(self):
        assert validate_telegram_webapp_data("not=a&valid=initdata") is None


class TestWebappAuthDecorator:
    async def test_valid_init_data_calls_handler_with_user(self):
        user = {"id": 42, "first_name": "Test"}
        init_data = build_init_data(user)
        called_with = {}

        @webapp_auth
        async def handler(request: web.Request) -> web.Response:
            called_with["telegram_user"] = request[TELEGRAM_USER_KEY]
            return web.json_response({"success": True})

        request = make_mocked_request(
            "GET", "/api/whatever", headers={"Authorization": init_data}
        )

        response = await handler(request)

        assert response.status == 200
        assert called_with["telegram_user"] == user

    async def test_invalid_init_data_returns_401_without_calling_handler(self):
        handler_called = False

        @webapp_auth
        async def handler(request: web.Request) -> web.Response:
            nonlocal handler_called
            handler_called = True
            return web.json_response({"success": True})

        request = make_mocked_request(
            "GET", "/api/whatever", headers={"Authorization": "garbage"}
        )

        response = await handler(request)

        assert response.status == 401
        assert handler_called is False

    async def test_missing_authorization_header_returns_401(self):
        @webapp_auth
        async def handler(request: web.Request) -> web.Response:
            return web.json_response({"success": True})

        request = make_mocked_request("GET", "/api/whatever")

        response = await handler(request)

        assert response.status == 401
