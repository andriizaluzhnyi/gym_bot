"""Tests for GYM-25: `Profile.water_tracking_enabled` round-tripping
through `GET`/`POST /api/user/settings` (src/webapp/server.py).
"""

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from src.database.models import Base
from src.database.repository import UserRepository
from src.database.session import async_session_maker, engine
from src.webapp.server import api_get_user_settings, api_update_user_settings
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


class TestDefaults:
    async def test_user_without_a_profile_row_defaults_to_enabled(self):
        """GYM-25: "профіль без рядка profiles (дефолти) → True"."""
        await _make_user(1)
        request = _mock_request("GET", "/api/user/settings", telegram_id=1)

        response = await api_get_user_settings(request)
        payload = json.loads(response.body)

        assert response.status == 200
        assert payload["data"]["water_tracking_enabled"] is True


class TestSettingsRoundTrip:
    async def test_disabling_persists_and_is_reflected_on_get(self):
        await _make_user(1)
        post_request = _mock_request(
            "POST", "/api/user/settings", telegram_id=1,
            body={"water_tracking_enabled": False},
        )
        post_response = await api_update_user_settings(post_request)
        post_payload = json.loads(post_response.body)

        assert post_response.status == 200
        assert post_payload["data"]["water_tracking_enabled"] is False

        get_request = _mock_request("GET", "/api/user/settings", telegram_id=1)
        get_response = await api_get_user_settings(get_request)
        get_payload = json.loads(get_response.body)

        assert get_payload["data"]["water_tracking_enabled"] is False

    async def test_re_enabling_restores_true_without_touching_the_goal(self):
        """GYM-25: "значення зберігається — при повторному увімкненні
        повертається" — daily_water_ml survives a disable/enable cycle.
        """
        await _make_user(1)

        await api_update_user_settings(_mock_request(
            "POST", "/api/user/settings", telegram_id=1,
            body={"daily_water_ml": 3000},
        ))
        await api_update_user_settings(_mock_request(
            "POST", "/api/user/settings", telegram_id=1,
            body={"water_tracking_enabled": False},
        ))
        disabled_response = await api_get_user_settings(
            _mock_request("GET", "/api/user/settings", telegram_id=1)
        )
        disabled_payload = json.loads(disabled_response.body)
        assert disabled_payload["data"]["water_tracking_enabled"] is False
        assert disabled_payload["data"]["daily_water_ml"] == 3000

        await api_update_user_settings(_mock_request(
            "POST", "/api/user/settings", telegram_id=1,
            body={"water_tracking_enabled": True},
        ))
        enabled_response = await api_get_user_settings(
            _mock_request("GET", "/api/user/settings", telegram_id=1)
        )
        enabled_payload = json.loads(enabled_response.body)

        assert enabled_payload["data"]["water_tracking_enabled"] is True
        assert enabled_payload["data"]["daily_water_ml"] == 3000

    async def test_omitting_the_field_does_not_change_it(self):
        await _make_user(1)
        await api_update_user_settings(_mock_request(
            "POST", "/api/user/settings", telegram_id=1,
            body={"water_tracking_enabled": False},
        ))

        # An update that doesn't mention water_tracking_enabled at all
        # (e.g. just editing calories) must leave it untouched.
        await api_update_user_settings(_mock_request(
            "POST", "/api/user/settings", telegram_id=1,
            body={"daily_calories": 2200},
        ))

        response = await api_get_user_settings(
            _mock_request("GET", "/api/user/settings", telegram_id=1)
        )
        payload = json.loads(response.body)

        assert payload["data"]["water_tracking_enabled"] is False
        assert payload["data"]["daily_calories"] == 2200
