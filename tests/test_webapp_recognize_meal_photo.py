"""Tests for GYM-23: `POST /api/nutrition/meal/photo`
(src/webapp/server.py).

Unlike most endpoint tests in this suite, these go through a real
`aiohttp.test_utils.TestClient`/`TestServer` instead of calling the
handler function directly — multipart parsing needs a genuine request
stream, which `make_mocked_request` doesn't provide. `recognize_food`
itself is mocked; its own OpenAI-calling behavior is covered by
`tests/test_food_recognition.py`.
"""

from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import select

from src.database.models import Base, DailyNutrition
from src.database.repository import UserRepository
from src.database.session import async_session_maker, engine
from src.services.food_recognition import FoodEstimate, FoodRecognitionError, NotFoodError
from src.webapp.server import create_webapp, settings
from tests.test_webapp_auth import build_init_data


@pytest.fixture(autouse=True)
async def _create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture(autouse=True)
def _openai_configured(monkeypatch):
    """Most tests need the feature "enabled"; the one test for the
    disabled case overrides this back to empty.
    """
    monkeypatch.setattr(settings, "openai_api_key", "test-key")


async def _make_user(telegram_id: int = 1):
    async with async_session_maker() as session:
        user, _ = await UserRepository(session).get_or_create(
            telegram_id=telegram_id, first_name="Test"
        )
        await session.commit()
        return user


@pytest.fixture
async def client():
    app = create_webapp()
    server = TestServer(app)
    test_client = TestClient(server)
    await test_client.start_server()
    yield test_client
    await test_client.close()


def _auth_headers(telegram_id: int = 1) -> dict:
    return {"Authorization": build_init_data({"id": telegram_id, "first_name": "Test"})}


def _photo_form(*, content: bytes = b"\xff\xd8\xff fake jpeg bytes", mime: str = "image/jpeg") -> FormData:
    form = FormData()
    form.add_field("photo", content, filename="meal.jpg", content_type=mime)
    return form


VALID_ESTIMATE = FoodEstimate(
    meal_name="Курка з рисом",
    portion_grams=350,
    protein=35,
    fats=12,
    carbs=45,
    calories=428,
    confidence="medium",
    notes="",
)


class TestAuthAndConfig:
    async def test_unauthorized_without_valid_init_data(self, client):
        resp = await client.post(
            "/api/nutrition/meal/photo",
            data=_photo_form(),
            headers={"Authorization": "garbage"},
        )
        assert resp.status == 401

    async def test_disabled_when_openai_api_key_is_empty(self, client, monkeypatch):
        monkeypatch.setattr(settings, "openai_api_key", "")
        await _make_user()

        resp = await client.post(
            "/api/nutrition/meal/photo", data=_photo_form(), headers=_auth_headers()
        )

        assert resp.status == 503
        payload = await resp.json()
        assert payload["error"] == "photo_recognition_disabled"

    async def test_does_not_call_openai_when_disabled(self, client, monkeypatch):
        monkeypatch.setattr(settings, "openai_api_key", "")
        await _make_user()

        with patch("src.webapp.server.recognize_food", new_callable=AsyncMock) as mock_recognize:
            await client.post(
                "/api/nutrition/meal/photo", data=_photo_form(), headers=_auth_headers()
            )
            mock_recognize.assert_not_awaited()


class TestValidation:
    async def test_missing_photo_field_returns_400(self, client):
        await _make_user()
        form = FormData()
        form.add_field(
            "not_photo", b"data", filename="data.bin",
            content_type="application/octet-stream",
        )

        resp = await client.post(
            "/api/nutrition/meal/photo", data=form, headers=_auth_headers()
        )
        assert resp.status == 400

    async def test_oversized_photo_returns_413(self, client):
        await _make_user()
        oversized = b"x" * (5 * 1024 * 1024 + 1)

        resp = await client.post(
            "/api/nutrition/meal/photo",
            data=_photo_form(content=oversized),
            headers=_auth_headers(),
        )
        assert resp.status == 413

    async def test_photo_at_exactly_the_limit_is_accepted(self, client):
        await _make_user()
        exactly_5mb = b"x" * (5 * 1024 * 1024)

        with patch(
            "src.webapp.server.recognize_food",
            new_callable=AsyncMock, return_value=VALID_ESTIMATE,
        ):
            resp = await client.post(
                "/api/nutrition/meal/photo",
                data=_photo_form(content=exactly_5mb),
                headers=_auth_headers(),
            )
        assert resp.status == 200

    async def test_unsupported_mime_type_returns_400(self, client):
        await _make_user()

        resp = await client.post(
            "/api/nutrition/meal/photo",
            data=_photo_form(mime="application/pdf"),
            headers=_auth_headers(),
        )
        assert resp.status == 400

    @pytest.mark.parametrize("mime", ["image/jpeg", "image/png", "image/webp", "image/heic"])
    async def test_allowed_mime_types_are_accepted(self, client, mime):
        await _make_user()

        with patch(
            "src.webapp.server.recognize_food",
            new_callable=AsyncMock, return_value=VALID_ESTIMATE,
        ):
            resp = await client.post(
                "/api/nutrition/meal/photo",
                data=_photo_form(mime=mime),
                headers=_auth_headers(),
            )
        assert resp.status == 200


class TestRecognitionOutcomes:
    async def test_success_returns_the_estimate(self, client):
        await _make_user()

        with patch(
            "src.webapp.server.recognize_food",
            new_callable=AsyncMock, return_value=VALID_ESTIMATE,
        ):
            resp = await client.post(
                "/api/nutrition/meal/photo", data=_photo_form(), headers=_auth_headers()
            )

        assert resp.status == 200
        payload = await resp.json()
        assert payload["success"] is True
        assert payload["data"] == {
            "meal_name": "Курка з рисом",
            "portion_grams": 350,
            "protein": 35,
            "fats": 12,
            "carbs": 45,
            "calories": 428,
            "confidence": "medium",
            "notes": "",
        }

    async def test_not_food_returns_422(self, client):
        await _make_user()

        with patch(
            "src.webapp.server.recognize_food",
            new_callable=AsyncMock, side_effect=NotFoodError("no food here"),
        ):
            resp = await client.post(
                "/api/nutrition/meal/photo", data=_photo_form(), headers=_auth_headers()
            )

        assert resp.status == 422
        payload = await resp.json()
        assert payload["error"] == "not_food"

    async def test_recognition_failure_returns_502_without_leaking_details(self, client):
        await _make_user()

        with patch(
            "src.webapp.server.recognize_food",
            new_callable=AsyncMock,
            side_effect=FoodRecognitionError("super secret internal detail"),
        ):
            resp = await client.post(
                "/api/nutrition/meal/photo", data=_photo_form(), headers=_auth_headers()
            )

        assert resp.status == 502
        payload = await resp.json()
        assert payload["error"] == "recognition_failed"
        assert "super secret internal detail" not in str(payload)

    async def test_never_writes_to_the_database(self, client):
        """AC: this endpoint never persists anything — no DailyNutrition
        row, regardless of outcome."""
        await _make_user()
        with patch(
            "src.webapp.server.recognize_food",
            new_callable=AsyncMock, return_value=VALID_ESTIMATE,
        ):
            await client.post(
                "/api/nutrition/meal/photo", data=_photo_form(), headers=_auth_headers()
            )

        async with async_session_maker() as session:
            result = await session.execute(select(DailyNutrition))
            assert result.scalars().all() == []
