"""Tests for GYM-23: src/services/food_recognition.py.

``parse_food_estimate`` is pure (no network/DB) — tested directly against
plain dicts. ``recognize_food`` (the OpenAI-calling half) is tested with
a mocked ``AsyncOpenAI`` client, covering the retry rule from the AC
(one retry on a timeout/5xx, none for anything else).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import APITimeoutError, AuthenticationError, InternalServerError, RateLimitError

from src.services.food_recognition import (
    FoodEstimate,
    FoodRecognitionError,
    InvalidEstimatePayloadError,
    NotFoodError,
    parse_food_estimate,
    recognize_food,
)

VALID_PAYLOAD = {
    "is_food": True,
    "meal_name": "Курка з рисом",
    "portion_grams": 350,
    "protein": 35,
    "fats": 12,
    "carbs": 45,
    "confidence": "medium",
    "notes": "Оцінка орієнтовна",
}


class TestParseFoodEstimateValid:
    def test_returns_a_food_estimate(self):
        estimate = parse_food_estimate(VALID_PAYLOAD)
        assert isinstance(estimate, FoodEstimate)
        assert estimate.meal_name == "Курка з рисом"
        assert estimate.portion_grams == 350
        assert estimate.protein == 35
        assert estimate.fats == 12
        assert estimate.carbs == 45
        assert estimate.confidence == "medium"
        assert estimate.notes == "Оцінка орієнтовна"

    def test_calories_is_always_derived_from_macros_via_4_9_4(self):
        # 35*4 + 12*9 + 45*4 = 140 + 108 + 180 = 428
        estimate = parse_food_estimate(VALID_PAYLOAD)
        assert estimate.calories == 428

    def test_model_reported_calories_field_is_ignored_if_present(self):
        payload = {**VALID_PAYLOAD, "calories": 9999}
        estimate = parse_food_estimate(payload)
        assert estimate.calories == 428  # derived, not the bogus 9999

    def test_missing_notes_defaults_to_empty_string(self):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "notes"}
        estimate = parse_food_estimate(payload)
        assert estimate.notes == ""

    def test_missing_meal_name_defaults_to_a_generic_label(self):
        payload = {**VALID_PAYLOAD, "meal_name": ""}
        estimate = parse_food_estimate(payload)
        assert estimate.meal_name == "Страва"


class TestParseFoodEstimateIsFood:
    def test_is_food_false_raises_not_food_error(self):
        payload = {**VALID_PAYLOAD, "is_food": False}
        with pytest.raises(NotFoodError):
            parse_food_estimate(payload)

    def test_is_food_true_does_not_raise(self):
        parse_food_estimate({**VALID_PAYLOAD, "is_food": True})  # no raise


class TestParseFoodEstimateIncomplete:
    @pytest.mark.parametrize(
        "missing_field", ["meal_name", "portion_grams", "protein", "fats", "carbs"]
    )
    def test_missing_required_field_raises(self, missing_field):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != missing_field}
        with pytest.raises(InvalidEstimatePayloadError):
            parse_food_estimate(payload)

    def test_wrong_type_for_numeric_field_raises(self):
        payload = {**VALID_PAYLOAD, "protein": "a lot"}
        with pytest.raises(InvalidEstimatePayloadError):
            parse_food_estimate(payload)

    def test_non_dict_payload_raises(self):
        with pytest.raises(InvalidEstimatePayloadError):
            parse_food_estimate("not a dict")  # type: ignore[arg-type]

    def test_invalid_confidence_falls_back_to_low(self):
        payload = {**VALID_PAYLOAD, "confidence": "extremely sure"}
        estimate = parse_food_estimate(payload)
        assert estimate.confidence == "low"

    def test_missing_confidence_falls_back_to_low(self):
        payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "confidence"}
        estimate = parse_food_estimate(payload)
        assert estimate.confidence == "low"


class TestParseFoodEstimateOutOfRange:
    def test_negative_portion_is_clamped_to_the_minimum(self):
        payload = {**VALID_PAYLOAD, "portion_grams": -50}
        estimate = parse_food_estimate(payload)
        assert estimate.portion_grams == 1

    def test_absurdly_large_portion_is_clamped_to_the_maximum(self):
        payload = {**VALID_PAYLOAD, "portion_grams": 1_000_000}
        estimate = parse_food_estimate(payload)
        assert estimate.portion_grams == 3000

    def test_negative_macro_is_clamped_to_zero(self):
        payload = {**VALID_PAYLOAD, "protein": -10}
        estimate = parse_food_estimate(payload)
        assert estimate.protein == 0

    def test_absurdly_large_macro_is_clamped(self):
        payload = {**VALID_PAYLOAD, "fats": 999999}
        estimate = parse_food_estimate(payload)
        assert estimate.fats == 500

    def test_calories_reflects_clamped_macros_not_raw_ones(self):
        payload = {**VALID_PAYLOAD, "protein": -10, "fats": 0, "carbs": 0}
        estimate = parse_food_estimate(payload)
        assert estimate.protein == 0
        assert estimate.calories == 0


def _mock_openai_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=json.dumps(payload)))]
    return response


class TestRecognizeFood:
    async def test_success_returns_parsed_estimate(self):
        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            return_value=_mock_openai_response(VALID_PAYLOAD)
        )
        with patch("src.services.food_recognition.AsyncOpenAI", return_value=client):
            estimate = await recognize_food(b"fake-bytes", "image/jpeg")

        assert estimate.meal_name == "Курка з рисом"
        client.chat.completions.create.assert_awaited_once()

    async def test_sends_the_image_as_a_data_url(self):
        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            return_value=_mock_openai_response(VALID_PAYLOAD)
        )
        with patch("src.services.food_recognition.AsyncOpenAI", return_value=client):
            await recognize_food(b"fake-bytes", "image/png")

        _, kwargs = client.chat.completions.create.call_args
        user_message = kwargs["messages"][1]
        image_block = next(
            c for c in user_message["content"] if c["type"] == "image_url"
        )
        assert image_block["image_url"]["url"].startswith("data:image/png;base64,")

    async def test_uses_json_schema_response_format(self):
        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            return_value=_mock_openai_response(VALID_PAYLOAD)
        )
        with patch("src.services.food_recognition.AsyncOpenAI", return_value=client):
            await recognize_food(b"fake-bytes", "image/jpeg")

        _, kwargs = client.chat.completions.create.call_args
        assert kwargs["response_format"]["type"] == "json_schema"

    async def test_not_food_response_raises_without_retry(self):
        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            return_value=_mock_openai_response({**VALID_PAYLOAD, "is_food": False})
        )
        with patch("src.services.food_recognition.AsyncOpenAI", return_value=client), pytest.raises(NotFoodError):
            await recognize_food(b"fake-bytes", "image/jpeg")

        client.chat.completions.create.assert_awaited_once()  # no retry

    async def test_timeout_is_retried_once_then_succeeds(self):
        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=[
                APITimeoutError(request=MagicMock()),
                _mock_openai_response(VALID_PAYLOAD),
            ]
        )
        with patch("src.services.food_recognition.AsyncOpenAI", return_value=client):
            estimate = await recognize_food(b"fake-bytes", "image/jpeg")

        assert estimate.meal_name == "Курка з рисом"
        assert client.chat.completions.create.await_count == 2

    async def test_internal_server_error_is_retried_once(self):
        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=[
                InternalServerError(
                    message="boom", response=MagicMock(status_code=500), body=None,
                ),
                _mock_openai_response(VALID_PAYLOAD),
            ]
        )
        with patch("src.services.food_recognition.AsyncOpenAI", return_value=client):
            estimate = await recognize_food(b"fake-bytes", "image/jpeg")

        assert estimate.meal_name == "Курка з рисом"
        assert client.chat.completions.create.await_count == 2

    async def test_persistent_timeout_raises_after_one_retry(self):
        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=APITimeoutError(request=MagicMock())
        )
        with patch("src.services.food_recognition.AsyncOpenAI", return_value=client), pytest.raises(FoodRecognitionError):
            await recognize_food(b"fake-bytes", "image/jpeg")

        assert client.chat.completions.create.await_count == 2  # 1 try + 1 retry, no more

    async def test_rate_limit_is_not_retried(self):
        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=RateLimitError(
                message="slow down", response=MagicMock(status_code=429), body=None,
            )
        )
        with patch("src.services.food_recognition.AsyncOpenAI", return_value=client), pytest.raises(FoodRecognitionError):
            await recognize_food(b"fake-bytes", "image/jpeg")

        client.chat.completions.create.assert_awaited_once()  # no retry

    async def test_authentication_error_is_not_retried(self):
        client = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=AuthenticationError(
                message="bad key", response=MagicMock(status_code=401), body=None,
            )
        )
        with patch("src.services.food_recognition.AsyncOpenAI", return_value=client), pytest.raises(FoodRecognitionError):
            await recognize_food(b"fake-bytes", "image/jpeg")

        client.chat.completions.create.assert_awaited_once()

    async def test_malformed_json_content_raises_food_recognition_error(self):
        client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content="not json"))]
        client.chat.completions.create = AsyncMock(return_value=response)
        with patch("src.services.food_recognition.AsyncOpenAI", return_value=client), pytest.raises(FoodRecognitionError):
            await recognize_food(b"fake-bytes", "image/jpeg")
