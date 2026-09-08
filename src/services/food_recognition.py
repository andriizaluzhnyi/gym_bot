"""GYM-23: photo -> macro-estimate recognition via OpenAI Vision.

Split the same way GYM-34's ``group_reminders.py`` is: a pure function
(``parse_food_estimate``) that turns the model's already-parsed JSON
response into a validated ``FoodEstimate`` — no network, no I/O, trivially
unit-testable — and a thin async function (``recognize_food``) that does
the actual OpenAI call and hands its response to the pure function.

Nothing here stores the photo or the estimate anywhere; the caller
(``api_recognize_meal_photo`` in ``src/webapp/server.py``) only ever holds
the uploaded bytes in memory for the duration of one request.
"""

import base64
import json
import logging
from dataclasses import dataclass

from openai import APITimeoutError, AsyncOpenAI, InternalServerError

from src.config import get_settings

logger = logging.getLogger(__name__)

_VALID_CONFIDENCE = {"low", "medium", "high"}
_PORTION_GRAMS_RANGE = (1.0, 3000.0)
_MACRO_GRAMS_RANGE = (0.0, 500.0)

# One retry, only for the transient cases named in the AC — anything else
# (bad request, auth, rate limit, content filter) is not worth repeating.
_RETRYABLE_ERRORS = (APITimeoutError, InternalServerError)
_MAX_ATTEMPTS = 2

_SYSTEM_PROMPT = (
    "Ти — нутриціолог-асистент, який оцінює харчову цінність їжі на фото. "
    "Завжди оцінюй ВСЮ видиму порцію на фото (а не одну ложку чи шматок), "
    "навіть якщо для цього потрібна прикидка на око. Якщо не впевнений у "
    "складі, способі приготування чи точній вазі — обирай нижчий рівень "
    "впевненості (confidence), а не завищуй її. Якщо на фото немає їжі "
    "(порожня тарілка, не їжа, надто нечітке фото) — постав is_food: "
    "false і залиш решту полів нульовими/порожніми."
)

_USER_PROMPT = (
    "Оціни харчову цінність їжі на цьому фото: назву страви, вагу порції "
    "в грамах, а також білки/жири/вуглеводи в грамах на всю видиму "
    "порцію, і рівень своєї впевненості в цій оцінці."
)

_RESPONSE_JSON_SCHEMA = {
    "name": "food_estimate",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "is_food": {"type": "boolean"},
            "meal_name": {"type": "string"},
            "portion_grams": {"type": "number"},
            "protein": {"type": "number"},
            "fats": {"type": "number"},
            "carbs": {"type": "number"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "notes": {"type": "string"},
        },
        "required": [
            "is_food", "meal_name", "portion_grams",
            "protein", "fats", "carbs", "confidence", "notes",
        ],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class FoodEstimate:
    """A validated macro estimate for one photographed meal."""

    meal_name: str
    portion_grams: float
    protein: float
    fats: float
    carbs: float
    calories: float
    confidence: str  # "low" | "medium" | "high"
    notes: str


class FoodRecognitionError(Exception):
    """Base class for every failure this module raises."""


class NotFoodError(FoodRecognitionError):
    """The model determined the photo doesn't show food (``is_food:
    false``) — a real, structured answer, just not a usable one.
    """


class InvalidEstimatePayloadError(FoodRecognitionError):
    """The model's JSON response was missing or had the wrong type for a
    required field — the response couldn't be trusted at all, unlike
    :class:`NotFoodError` where the model *did* answer meaningfully.
    """


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    low, high = bounds
    return max(low, min(high, value))


def parse_food_estimate(payload: dict) -> FoodEstimate:
    """Pure function: OpenAI's parsed JSON response -> a validated
    ``FoodEstimate``.

    Raises:
        NotFoodError: ``is_food`` is ``False``.
        InvalidEstimatePayloadError: a required field is missing or the
            wrong type.

    Numeric fields outside a plausible range are clamped rather than
    rejected — an implausible number next to a "low" confidence is still
    useful signal, not a reason to discard the whole estimate.
    ``calories`` is always *derived* from the (clamped) macros via the
    same 4/9/4 rule ``meal_entry.html``'s ``calculateCalories()`` uses
    client-side, never taken from the model directly: a model-reported
    number that disagrees with its own macros is exactly the kind of
    small arithmetic slip an LLM makes, and unconditionally recomputing
    it is simpler than a "check, then maybe recompute" branch that would
    produce the identical result whenever the model's number already
    happened to agree.
    """
    if not isinstance(payload, dict):
        raise InvalidEstimatePayloadError("Response payload is not a JSON object")

    if payload.get("is_food") is False:
        raise NotFoodError("Model determined the photo does not show food")

    try:
        meal_name = str(payload["meal_name"]).strip() or "Страва"
        portion_grams = float(payload["portion_grams"])
        protein = float(payload["protein"])
        fats = float(payload["fats"])
        carbs = float(payload["carbs"])
    except (KeyError, TypeError, ValueError) as e:
        raise InvalidEstimatePayloadError(
            f"Missing or invalid required field: {e}"
        ) from e

    confidence = payload.get("confidence")
    if confidence not in _VALID_CONFIDENCE:
        confidence = "low"

    notes = str(payload.get("notes") or "").strip()

    portion_grams = _clamp(portion_grams, _PORTION_GRAMS_RANGE)
    protein = _clamp(protein, _MACRO_GRAMS_RANGE)
    fats = _clamp(fats, _MACRO_GRAMS_RANGE)
    carbs = _clamp(carbs, _MACRO_GRAMS_RANGE)
    calories = round(protein * 4 + fats * 9 + carbs * 4)

    return FoodEstimate(
        meal_name=meal_name,
        portion_grams=portion_grams,
        protein=protein,
        fats=fats,
        carbs=carbs,
        calories=calories,
        confidence=confidence,
        notes=notes,
    )


async def recognize_food(image_bytes: bytes, mime: str) -> FoodEstimate:
    """Send ``image_bytes`` to OpenAI Vision and return a validated macro
    estimate.

    Retries once on a timeout or a 5xx from OpenAI (per the AC); any
    other OpenAI-side error, or a malformed/incomplete JSON response,
    raises immediately. Callers should catch ``NotFoodError`` (-> 422)
    and ``FoodRecognitionError`` (-> 502) separately — see
    ``api_recognize_meal_photo``.
    """
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _USER_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]

    last_error: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            # The SDK's overloads want a stricter TypedDict shape than a
            # plain dict literal built from local prompt strings satisfies
            # statically; the request body is correct at runtime (this is
            # the documented vision + structured-output request shape).
            response = await client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                response_format={"type": "json_schema", "json_schema": _RESPONSE_JSON_SCHEMA},
                timeout=30,
            )  # type: ignore[call-overload]
            content = response.choices[0].message.content
            payload = json.loads(content)
            return parse_food_estimate(payload)
        except (NotFoodError, InvalidEstimatePayloadError):
            raise  # the model answered — retrying won't change that
        except _RETRYABLE_ERRORS as e:
            last_error = e
            logger.warning(
                f"OpenAI food recognition attempt {attempt}/{_MAX_ATTEMPTS} "
                f"failed ({type(e).__name__}): {e}"
            )
        except Exception as e:
            # Non-retryable (auth, bad request, rate limit, ...) — fail now.
            logger.warning(f"OpenAI food recognition failed: {e}")
            raise FoodRecognitionError(str(e)) from e

    raise FoodRecognitionError(
        f"OpenAI request failed after {_MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error
