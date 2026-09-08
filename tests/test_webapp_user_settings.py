"""Tests for GYM-26: `notifications_enabled` round-tripping through
`GET`/`POST /api/user/settings` (src/webapp/server.py), and the
`@webapp_auth` conversion of both endpoints.
"""

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.database.models import Base
from src.database.repository import UserRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import api_get_user_settings, api_update_user_settings, settings
from tests.test_webapp_auth import build_init_data


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _make_user(telegram_id: int):
    async with async_session_maker() as session:
        user, _ = await UserRepository(session).get_or_create(
            telegram_id=telegram_id, first_name="Test"
        )
        await session.commit()
        return user


def _mock_request(method: str, path: str, *, telegram_id: int, body: dict | None = None) -> web.Request:
    init_data = build_init_data({"id": telegram_id, "first_name": "Test"})
    request = make_mocked_request(method, path, headers={"Authorization": init_data})
    if body is not None:
        async def fake_json():
            return body
        request.json = fake_json  # type: ignore[method-assign, assignment]
    return request


class TestAuth:
    async def test_get_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "GET", "/api/user/settings", headers={"Authorization": "garbage"}
        )
        response = await api_get_user_settings(request)
        assert response.status == 401

    async def test_post_unauthorized_without_valid_init_data(self):
        request = make_mocked_request(
            "POST", "/api/user/settings", headers={"Authorization": "garbage"}
        )
        response = await api_update_user_settings(request)
        assert response.status == 401

    async def test_get_unknown_user_returns_404(self):
        request = _mock_request("GET", "/api/user/settings", telegram_id=999)
        response = await api_get_user_settings(request)
        assert response.status == 404

    async def test_post_unknown_user_returns_404(self):
        request = _mock_request(
            "POST", "/api/user/settings", telegram_id=999, body={}
        )
        response = await api_update_user_settings(request)
        assert response.status == 404


class TestNotificationsEnabledDefaults:
    async def test_defaults_to_enabled(self):
        await _make_user(1)
        request = _mock_request("GET", "/api/user/settings", telegram_id=1)

        response = await api_get_user_settings(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload["data"]["notifications_enabled"] is True

    async def test_defaults_to_enabled_even_without_a_profile_row(self):
        """User.notifications_enabled doesn't depend on Profile existing —
        the no-profile-yet branch of get_nutrition_settings must include
        it too."""
        await _make_user(1)
        request = _mock_request("GET", "/api/user/settings", telegram_id=1)
        response = await api_get_user_settings(request)
        payload = json.loads(response.body)

        # No profile row was ever created (no POST was made) — still True.
        assert payload["data"]["notifications_enabled"] is True


class TestPhotoRecognitionEnabled:
    """GYM-23: a global app setting (bool(settings.openai_api_key)), not
    per-user — included in GET /api/user/settings so the WebApp knows
    whether to show the "📷 Фото" button at all.
    """

    async def test_true_when_openai_api_key_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "openai_api_key", "sk-test-key")
        await _make_user(1)
        request = _mock_request("GET", "/api/user/settings", telegram_id=1)

        response = await api_get_user_settings(request)
        payload = json.loads(response.body)

        assert payload["data"]["photo_recognition_enabled"] is True

    async def test_false_when_openai_api_key_missing(self, monkeypatch):
        monkeypatch.setattr(settings, "openai_api_key", "")
        await _make_user(1)
        request = _mock_request("GET", "/api/user/settings", telegram_id=1)

        response = await api_get_user_settings(request)
        payload = json.loads(response.body)

        assert payload["data"]["photo_recognition_enabled"] is False


class TestNotificationsEnabledRoundTrip:
    async def test_disabling_persists_and_is_reflected_on_get(self):
        await _make_user(1)
        post_response = await api_update_user_settings(_mock_request(
            "POST", "/api/user/settings", telegram_id=1,
            body={"notifications_enabled": False},
        ))
        post_payload = json.loads(post_response.body)

        assert post_response.status == 200
        assert post_payload["data"]["notifications_enabled"] is False

        get_response = await api_get_user_settings(
            _mock_request("GET", "/api/user/settings", telegram_id=1)
        )
        get_payload = json.loads(get_response.body)
        assert get_payload["data"]["notifications_enabled"] is False

    async def test_re_enabling_works(self):
        await _make_user(1)
        await api_update_user_settings(_mock_request(
            "POST", "/api/user/settings", telegram_id=1,
            body={"notifications_enabled": False},
        ))
        await api_update_user_settings(_mock_request(
            "POST", "/api/user/settings", telegram_id=1,
            body={"notifications_enabled": True},
        ))

        response = await api_get_user_settings(
            _mock_request("GET", "/api/user/settings", telegram_id=1)
        )
        payload = json.loads(response.body)
        assert payload["data"]["notifications_enabled"] is True

    async def test_omitting_the_field_does_not_change_it(self):
        await _make_user(1)
        await api_update_user_settings(_mock_request(
            "POST", "/api/user/settings", telegram_id=1,
            body={"notifications_enabled": False},
        ))

        # An update that doesn't mention notifications_enabled at all
        # (e.g. just editing calories) must leave it untouched.
        await api_update_user_settings(_mock_request(
            "POST", "/api/user/settings", telegram_id=1,
            body={"daily_calories": 2200},
        ))

        response = await api_get_user_settings(
            _mock_request("GET", "/api/user/settings", telegram_id=1)
        )
        payload = json.loads(response.body)

        assert payload["data"]["notifications_enabled"] is False
        assert payload["data"]["daily_calories"] == 2200

    async def test_persisted_directly_on_the_user_row(self):
        user = await _make_user(1)
        await api_update_user_settings(_mock_request(
            "POST", "/api/user/settings", telegram_id=1,
            body={"notifications_enabled": False},
        ))

        async with async_session_maker() as session:
            reloaded = await UserRepository(session).get_by_telegram_id(
                user.telegram_id
            )
        assert reloaded.notifications_enabled is False
