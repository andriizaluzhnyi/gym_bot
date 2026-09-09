"""Web server for Telegram Mini App."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from aiohttp import BodyPartReader, web
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database.repository import (
    DailyNutritionRepository,
    ExerciseRepository,
    PhotoRecognitionLogRepository,
    ProfileRepository,
    UserAchievementRepository,
    UserRepository,
    WorkoutProgramRepository,
    WorkoutSessionRepository,
    WorkoutSetRepository,
)
from src.database.models import NutritionEntryType, User
from src.database.session import async_session_maker
from src.services.google_calendar import GoogleCalendarService
from src.services.google_sheets import GoogleSheetsService
from src.services.achievements import ACHIEVEMENTS, AchievementsService
from src.services.food_recognition import (
    FoodRecognitionError,
    NotFoodError,
    recognize_food,
)
from src.services.personal_records import calculate_prs
from src.services.rest_timer import should_send_rest_reminder
from src.services.streak import calculate_streak
from src.services.workout_program_parsing import MUSCLE_GROUPS, is_valid_sets_reps
from src.utils.datetime_utils import period_bounds_utc, to_local_date, utcnow
from src.webapp.auth import TELEGRAM_USER_KEY, validate_telegram_webapp_data, webapp_auth

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / 'templates'
settings = get_settings()

# Global bot instance (will be set by run_bot)
_bot_instance = None

# GYM-34: the bot's own @username, cached once at startup via
# `bot.get_me()` (see `set_bot_username`) rather than an env var — used
# to build `https://t.me/<bot>?start=...` deep links in group reminder
# messages (`src/services/group_reminders.py`).
_bot_username: str | None = None


def set_bot_instance(bot):
    """Set the global bot instance."""
    global _bot_instance
    _bot_instance = bot


def get_bot_instance():
    """Get the global bot instance."""
    return _bot_instance


def set_bot_username(username: str | None) -> None:
    """Cache the bot's own @username (GYM-34) — set once from
    ``bot.get_me()`` in ``run_bot()``, alongside ``set_bot_instance``.
    """
    global _bot_username
    _bot_username = username


# GYM-47: pending rest-timer reminder tasks, keyed by the *caller's*
# Telegram id (not the workout's `user` — a trainer running a rest timer
# for a client's session still gets their own reminder). One process, one
# in-memory registry — the bot and this webapp share a process
# (`get_bot_instance()`), so this is enough to cancel a still-pending
# reminder from `POST /api/workout/log` or a manual stop
# (`DELETE /api/workout/rest-timer`) without a persistent job queue. Lost
# on process restart, which is fine: a lost reminder just doesn't fire —
# no orphaned notification, nothing to reconcile on the way back up.
_rest_timer_tasks: dict[int, asyncio.Task] = {}


def _cancel_rest_timer(telegram_user_id: int) -> None:
    """Cancel `telegram_user_id`'s pending rest-timer reminder, if any.

    Used when a fresh timer replaces a still-waiting one for the same
    user, when their workout is saved (`api_save_workout_log`), and by the
    explicit manual-stop endpoint (`api_cancel_rest_timer`).
    """
    task = _rest_timer_tasks.pop(telegram_user_id, None)
    if task is not None and not task.done():
        task.cancel()


def get_bot_username() -> str | None:
    """The cached bot @username (GYM-34), or ``None`` if it hasn't been
    set yet (e.g. this code path is reached before ``run_bot()`` calls
    ``set_bot_username``, or in a test that never called it).
    """
    return _bot_username


async def nutrition_handler(request: web.Request) -> web.StreamResponse:
    """Serve the nutrition tracking Mini App."""
    html_path = TEMPLATES_DIR / 'nutrition.html'
    return web.FileResponse(html_path)


async def profile_handler(request: web.Request) -> web.StreamResponse:
    """Serve the profile Mini App."""
    html_path = TEMPLATES_DIR / 'profile.html'
    return web.FileResponse(html_path)


async def meal_entry_handler(request: web.Request) -> web.StreamResponse:
    """Serve the meal entry Mini App."""
    html_path = TEMPLATES_DIR / 'meal_entry.html'
    return web.FileResponse(html_path)


@webapp_auth
async def api_get_user_settings(request: web.Request) -> web.Response:
    """API endpoint to get user nutrition/body settings, plus
    ``notifications_enabled`` (GYM-26) and ``photo_recognition_enabled``
    (GYM-23 — a global app setting, not per-user, so the WebApp knows
    whether to show the "📷 Фото" button at all) — the WebApp profile
    screen's single combined read.

    Expects Authorization header with Telegram initData.
    """
    telegram_id = request[TELEGRAM_USER_KEY].get('id')
    if not telegram_id:
        return web.json_response({'error': 'Invalid user data'}, status=400)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        nutrition = await user_repo.get_nutrition_settings(telegram_id)

        if not nutrition:
            return web.json_response({'error': 'User not found'}, status=404)

        nutrition['photo_recognition_enabled'] = bool(settings.openai_api_key)

        return web.json_response({
            'success': True,
            'data': nutrition
        })


@webapp_auth
async def api_update_user_settings(request: web.Request) -> web.Response:
    """API endpoint to update user nutrition/body settings and
    ``notifications_enabled`` (GYM-26; a ``User`` column, set via
    ``UserRepository.set_notifications_enabled`` rather than
    ``update_nutrition_settings``, which only ever touched ``Profile``).

    Expects Authorization header with Telegram initData.
    """
    telegram_id = request[TELEGRAM_USER_KEY].get('id')
    if not telegram_id:
        return web.json_response({'error': 'Invalid user data'}, status=400)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({'error': 'Invalid JSON'}, status=400)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)

        # Update user nutrition/body goals
        user = await user_repo.update_nutrition_settings(
            telegram_id=telegram_id,
            age=body.get('age'),
            height=body.get('height'),
            weight=body.get('weight'),
            gender=body.get('gender'),
            water_tracking_enabled=body.get('water_tracking_enabled'),
            daily_water_ml=body.get('daily_water_ml'),
            daily_calories=body.get('daily_calories'),
            daily_protein=body.get('daily_protein'),
            daily_fats=body.get('daily_fats'),
            daily_carbs=body.get('daily_carbs'),
        )
        if not user:
            return web.json_response({'error': 'User not found'}, status=404)

        if body.get('notifications_enabled') is not None:
            await user_repo.set_notifications_enabled(
                telegram_id, bool(body['notifications_enabled'])
            )

        await session.commit()

        nutrition = await user_repo.get_nutrition_settings(telegram_id)
        return web.json_response({
            'success': True,
            'data': nutrition
        })


async def api_save_daily_nutrition(request: web.Request) -> web.Response:
    """API endpoint to save daily nutrition data.

    Expects Authorization header with Telegram initData.
    """
    init_data = request.headers.get('Authorization', '')
    user_data = validate_telegram_webapp_data(init_data)

    if not user_data:
        return web.json_response({'error': 'Unauthorized'}, status=401)

    telegram_id = user_data.get('id')
    if not telegram_id:
        return web.json_response({'error': 'Invalid user data'}, status=400)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({'error': 'Invalid JSON'}, status=400)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        daily_nutrition_repo = DailyNutritionRepository(session)

        # Get user
        user = await user_repo.get_by_telegram_id(telegram_id)
        if not user:
            return web.json_response({'error': 'User not found'}, status=404)

        # Save daily nutrition record (increment only) — GYM-21: explicit
        # entry_type, this endpoint only ever logs water.
        record = await daily_nutrition_repo.create(
            user_id=user.id,
            date=utcnow(),
            entry_type=NutritionEntryType.WATER.value,
            water_ml=body.get('water_ml'),
            calories=body.get('calories'),
            protein=body.get('protein'),
            fats=body.get('fats'),
            carbs=body.get('carbs'),
        )

        await session.commit()

        return web.json_response({
            'success': True,
            'data': {
                'id': record.id,
                'date': record.date.isoformat(),
                'water_ml': record.water_ml,
                'calories': record.calories,
                'protein': record.protein,
                'fats': record.fats,
                'carbs': record.carbs,
            }
        })


async def api_get_daily_nutrition(request: web.Request) -> web.Response:
    """API endpoint to get today's nutrition data.

    Expects Authorization header with Telegram initData.
    """
    init_data = request.headers.get('Authorization', '')
    user_data = validate_telegram_webapp_data(init_data)

    if not user_data:
        return web.json_response({'error': 'Unauthorized'}, status=401)

    telegram_id = user_data.get('id')
    if not telegram_id:
        return web.json_response({'error': 'Invalid user data'}, status=400)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        daily_nutrition_repo = DailyNutritionRepository(session)

        # Get user
        user = await user_repo.get_by_telegram_id(telegram_id)
        if not user:
            return web.json_response({'error': 'User not found'}, status=404)

        # Get today's total (sum of all records) — GYM-21: "today" is the
        # local calendar day (settings.timezone), not the UTC day.
        totals = await daily_nutrition_repo.get_today_total(
            user.id, settings.timezone
        )

        # GYM-22: `date` lets the client render "today" without computing
        # it from the device's own clock/timezone (which may not match
        # settings.timezone); `last_water_entry_id` lets "↩️ Відмінити"
        # delete the right row (GYM-21) even right after a page reload,
        # with no client-side history to reconstruct it from.
        last_water_entry_id = await daily_nutrition_repo.get_last_entry_id_for_local_day(
            user.id, settings.timezone, NutritionEntryType.WATER.value
        )
        totals['date'] = to_local_date(utcnow(), settings.timezone).isoformat()
        totals['last_water_entry_id'] = last_water_entry_id

        return web.json_response({
            'success': True,
            'data': totals
        })


async def api_add_meal(request: web.Request) -> web.Response:
    """API endpoint to add a meal entry.

    Expects Authorization header with Telegram initData.
    """
    init_data = request.headers.get('Authorization', '')
    user_data = validate_telegram_webapp_data(init_data)

    if not user_data:
        return web.json_response({'error': 'Unauthorized'}, status=401)

    telegram_id = user_data.get('id')
    if not telegram_id:
        return web.json_response({'error': 'Invalid user data'}, status=400)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({'error': 'Invalid JSON'}, status=400)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        daily_nutrition_repo = DailyNutritionRepository(session)

        # Get user
        user = await user_repo.get_by_telegram_id(telegram_id)
        if not user:
            return web.json_response({'error': 'User not found'}, status=404)

        # Create meal record — GYM-21: entry_type is now explicit (not
        # inferred from water_ml == 0) and meal_name is actually persisted
        # instead of only being echoed back in the response.
        record = await daily_nutrition_repo.create(
            user_id=user.id,
            date=utcnow(),
            entry_type=NutritionEntryType.MEAL.value,
            meal_name=body.get('meal_name'),
            water_ml=0,
            calories=body.get('calories', 0),
            protein=body.get('protein', 0),
            fats=body.get('fats', 0),
            carbs=body.get('carbs', 0),
        )

        await session.commit()

        return web.json_response({
            'success': True,
            'data': {
                'id': record.id,
                'meal_name': record.meal_name,
                'calories': record.calories,
                'protein': record.protein,
                'fats': record.fats,
                'carbs': record.carbs,
                'created_at': record.created_at.isoformat(),
            }
        })


_MAX_MEAL_PHOTO_BYTES = 5 * 1024 * 1024
_ALLOWED_MEAL_PHOTO_MIME_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/heic'}


async def _read_meal_photo_field(
    request: web.Request,
) -> tuple[bytes | None, str | None, str | None]:
    """Pull the `photo` field out of a multipart request, capping the
    read at `_MAX_MEAL_PHOTO_BYTES` (checked as the bytes come in, not
    just via the possibly-absent/spoofable `Content-Length` header).

    Returns `(image_bytes, mime, error_code)` — exactly one of the first
    two or the third is set. `error_code` is one of `"missing_photo"` /
    `"too_large"`.
    """
    reader = await request.multipart()
    field = None
    async for part in reader:
        if isinstance(part, BodyPartReader) and part.name == 'photo':
            field = part
            break

    if field is None:
        return None, None, 'missing_photo'

    chunks = []
    total = 0
    while True:
        chunk = await field.read_chunk(size=65536)
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_MEAL_PHOTO_BYTES:
            return None, None, 'too_large'
        chunks.append(chunk)

    mime = (field.headers.get('Content-Type') or '').split(';')[0].strip().lower()
    return b''.join(chunks), mime, None


@webapp_auth
async def api_recognize_meal_photo(request: web.Request) -> web.Response:
    """API endpoint (GYM-23): estimate a meal's macros from a photo via
    OpenAI Vision. Never persists the photo or the estimate anywhere —
    the client shows the result on ``/meal-entry`` for the user to review
    and edit before an explicit ``POST /api/nutrition/meal`` (GYM-21/24).

    Body: multipart/form-data, one field `photo` (≤ 5 MB,
    image/jpeg|png|webp|heic).
    Expects Authorization header with Telegram initData.

    GYM-43: capped at ``settings.openai_daily_photo_limit`` (default 5)
    attempts per user per *local* calendar day (same boundary as
    ``DailyNutrition``'s "today", GYM-21) — checked before any of the
    validation below so a user who already hit it doesn't pay for a
    multipart parse for nothing. The counter only advances for requests
    that actually reach ``recognize_food`` (a real OpenAI call): a
    ``400``/``413``/``503`` below never counts, but a ``422``/``502`` after
    the call does, same as a ``200`` — the cost was already spent either
    way.
    """
    if not settings.openai_api_key:
        return web.json_response(
            {'error': 'photo_recognition_disabled'}, status=503
        )

    telegram_id = request[TELEGRAM_USER_KEY].get('id')
    if not telegram_id:
        return web.json_response({'error': 'Invalid user data'}, status=400)

    async with async_session_maker() as session:
        user = await UserRepository(session).get_by_telegram_id(telegram_id)
        if not user:
            return web.json_response({'error': 'User not found'}, status=404)

        photo_log_repo = PhotoRecognitionLogRepository(session)
        limit = settings.openai_daily_photo_limit
        used = await photo_log_repo.count_for_local_day(user.id, settings.timezone)
        if used >= limit:
            _, reset_at = period_bounds_utc("day", settings.timezone)
            assert reset_at is not None  # period="day" always returns bounds
            return web.json_response({
                'error': 'daily_photo_limit_exceeded',
                'limit': limit,
                'reset_at': reset_at.isoformat(),
            }, status=429)

        try:
            image_bytes, mime, error_code = await _read_meal_photo_field(request)
        except Exception as e:
            logger.warning(f'Failed to read meal photo upload: {e}')
            return web.json_response({'error': 'Invalid multipart body'}, status=400)

        if error_code == 'missing_photo':
            return web.json_response(
                {'error': "Missing required multipart field: photo"}, status=400
            )
        if error_code == 'too_large':
            return web.json_response({'error': 'Photo exceeds 5MB limit'}, status=413)

        assert image_bytes is not None and mime is not None  # no error_code above fired

        if mime not in _ALLOWED_MEAL_PHOTO_MIME_TYPES:
            return web.json_response(
                {'error': f'Unsupported photo type: {mime or "unknown"}'}, status=400
            )

        # From here on, the request reaches recognize_food (an actual
        # OpenAI call) no matter the outcome — log the attempt now so a
        # failure/exception in recognize_food can't skip the count.
        await photo_log_repo.create(user.id)
        await session.commit()

        try:
            estimate = await recognize_food(image_bytes, mime)
        except NotFoodError:
            return web.json_response({'error': 'not_food'}, status=422)
        except FoodRecognitionError as e:
            logger.warning(f'Food recognition failed: {e}')
            return web.json_response({'error': 'recognition_failed'}, status=502)

    return web.json_response({
        'success': True,
        'data': {
            'meal_name': estimate.meal_name,
            'portion_grams': estimate.portion_grams,
            'protein': estimate.protein,
            'fats': estimate.fats,
            'carbs': estimate.carbs,
            'calories': estimate.calories,
            'confidence': estimate.confidence,
            'notes': estimate.notes,
        },
    })


async def api_get_today_meals(request: web.Request) -> web.Response:
    """API endpoint to get today's meals list.

    Expects Authorization header with Telegram initData.
    """
    init_data = request.headers.get('Authorization', '')
    user_data = validate_telegram_webapp_data(init_data)

    if not user_data:
        return web.json_response({'error': 'Unauthorized'}, status=401)

    telegram_id = user_data.get('id')
    if not telegram_id:
        return web.json_response({'error': 'Invalid user data'}, status=400)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        daily_nutrition_repo = DailyNutritionRepository(session)

        # Get user
        user = await user_repo.get_by_telegram_id(telegram_id)
        if not user:
            return web.json_response({'error': 'User not found'}, status=404)

        # GYM-21: filters by the explicit entry_type column (not
        # water_ml == 0) and by the local calendar day (not UTC).
        meals = await daily_nutrition_repo.get_meals_for_local_day(
            user.id, settings.timezone
        )

        return web.json_response({
            'success': True,
            'data': [
                {
                    'id': meal.id,
                    'meal_name': meal.meal_name,
                    'calories': meal.calories,
                    'protein': meal.protein,
                    'fats': meal.fats,
                    'carbs': meal.carbs,
                    'created_at': meal.created_at.isoformat(),
                }
                for meal in meals
            ]
        })


@webapp_auth
async def api_delete_meal(request: web.Request) -> web.Response:
    """API endpoint to delete one logged entry (meal or water) — GYM-21.

    Path param: `id`. Deletes only if the entry belongs to the caller;
    otherwise (missing, or someone else's entry) responds 404 without
    distinguishing the two, same as the workout history/session endpoints.
    Expects Authorization header with Telegram initData.
    """
    entry_id_raw = request.match_info.get('id', '')
    if not entry_id_raw.isdigit():
        return web.json_response({'error': 'Invalid id'}, status=400)
    entry_id = int(entry_id_raw)

    telegram_id = request[TELEGRAM_USER_KEY].get('id')
    if not telegram_id:
        return web.json_response({'error': 'Invalid user data'}, status=400)

    async with async_session_maker() as session:
        user = await UserRepository(session).get_by_telegram_id(telegram_id)
        if not user:
            return web.json_response({'error': 'User not found'}, status=404)

        deleted = await DailyNutritionRepository(session).delete_by_id_for_user(
            entry_id, user.id
        )
        if not deleted:
            return web.json_response({'error': 'Entry not found'}, status=404)

        await session.commit()

        return web.json_response({'success': True})


_VALID_NUTRITION_PERIODS = ('week', 'month')


@webapp_auth
async def api_get_nutrition_statistics(request: web.Request) -> web.Response:
    """API endpoint (GYM-14/GYM-16): daily calorie/macro/water totals over
    a period, one entry per local calendar day (`settings.timezone`) — a
    day with no logged record gets zeros rather than being omitted, so the
    response always covers every day of the period (7 for a week, however
    many days are in the current month) ready for a bar chart with no
    client-side gap-filling (GYM-15). Also includes `avg_vs_goal`: how far
    the period's average is from each `Profile.daily_*` goal, for the
    "insight" line above the chart (GYM-16).

    Unlike the `/api/statistics/*` workout endpoints, there's no `?user=`
    trainer-viewing-a-client convention here — nutrition data is always
    the caller's own, same as the other `/api/nutrition/*` endpoints.

    Query params: `period=week|month` (default `week`).
    Expects Authorization header with Telegram initData.
    """
    period = request.query.get('period', 'week')
    if period not in _VALID_NUTRITION_PERIODS:
        return web.json_response(
            {'error': "Invalid period: must be 'week' or 'month'"}, status=400
        )

    telegram_id = request[TELEGRAM_USER_KEY].get('id')
    if not telegram_id:
        return web.json_response({'error': 'Invalid user data'}, status=400)

    async with async_session_maker() as session:
        user = await UserRepository(session).get_by_telegram_id(telegram_id)
        if not user:
            return web.json_response({'error': 'User not found'}, status=404)

        start, end = period_bounds_utc(period, settings.timezone)
        # period is validated to be 'week' or 'month' above, so
        # period_bounds_utc never takes its (None, None)-returning "all"
        # branch — this is just narrowing the type for mypy.
        assert start is not None and end is not None
        totals_by_day = await DailyNutritionRepository(session).get_totals_by_range(
            user.id, start, end, settings.timezone
        )
        profile = await ProfileRepository(session).get_by_user_id(user.id)

    by_day = []
    day = to_local_date(start, settings.timezone)
    end_day = to_local_date(end, settings.timezone)
    while day < end_day:
        totals = totals_by_day.get(day, {
            'calories': 0, 'protein': 0, 'fats': 0, 'carbs': 0, 'water_ml': 0,
        })
        by_day.append({'date': day.isoformat(), **totals})
        day += timedelta(days=1)

    avg_vs_goal = _compute_avg_vs_goal(totals_by_day, profile)

    return web.json_response({
        'success': True,
        'data': {'by_day': by_day, 'avg_vs_goal': avg_vs_goal},
    })


#: Same fallback goals as UserRepository.get_nutrition_settings (used
#: while a user has no Profile row yet — a fresh Profile() gets these via
#: the model's own column defaults instead, see models.py).
_DEFAULT_NUTRITION_GOALS = {
    'calories': 2500, 'protein': 150, 'fats': 80, 'carbs': 250,
}


def _compute_avg_vs_goal(
    totals_by_day: dict, profile
) -> dict | None:
    """GYM-16: how far the period's average daily calories/protein/fats/
    carbs sit from the user's `Profile.daily_*` goals, as a percentage —
    negative under goal, positive over. Days with no logged record are
    excluded from the average (`totals_by_day` only holds days that have
    at least one, per `get_totals_by_range`). `None` when the period has
    no logged days at all — nothing to compare yet.
    """
    days = list(totals_by_day.values())
    if not days:
        return None

    result = {}
    for metric in ('calories', 'protein', 'fats', 'carbs'):
        goal = getattr(profile, f'daily_{metric}', None) if profile else None
        if goal is None:
            goal = _DEFAULT_NUTRITION_GOALS[metric]

        avg = sum(day[metric] for day in days) / len(days)
        # A goal of exactly 0 (a user explicitly zeroing it out) has no
        # meaningful "% of goal" — leave that metric out rather than
        # divide by zero.
        result[f'{metric}_diff_pct'] = (
            round((avg - goal) / goal * 100, 1) if goal else None
        )
    return result


async def workout_handler(request: web.Request) -> web.StreamResponse:
    """Serve the workout tracking Mini App."""
    html_path = TEMPLATES_DIR / 'workout.html'
    return web.FileResponse(html_path)


async def statistics_handler(request: web.Request) -> web.StreamResponse:
    """Serve the workout statistics Mini App (GYM-3).

    A summary strip plus tabs for volume/exercise-progress/activity, each
    backed by its own ticket's ``/api/statistics/*`` endpoint — volume
    (GYM-4) and the summary strip (GYM-6) are wired up; the exercise-progress
    and activity tabs are still placeholders pending GYM-5a/GYM-5b. Like the
    other Mini App pages, auth happens client-side via ``initData`` on the
    API calls the page makes, not here.
    """
    html_path = TEMPLATES_DIR / 'statistics.html'
    return web.FileResponse(html_path)


_VALID_STATISTICS_PERIODS = ('week', 'month', 'all')


async def _resolve_program_owner(
    session: AsyncSession, request: web.Request, param_user: str | None
) -> User | web.Response:
    """Resolve whose workout data a `/api/statistics/*` or program request
    (`/api/workout/program`, `/api/workout/day`, `/api/workout/exercise`)
    is for — and enforce that only an admin may look at anyone else's
    (GYM-28: closes the "`is_admin()` stubbed out" risk carried over from
    phase 1 — every one of these endpoints previously trusted `?user=`
    from *any* authenticated caller with no ownership check at all).

    Defaults to the caller's own `telegram_id` (from `initData`, via
    `@webapp_auth`) when `param_user` is absent — same convention as
    before. Returns the resolved ``User`` on success, or a ready-to-return
    error ``web.Response`` otherwise: `403` if `param_user` names someone
    other than the caller and the caller isn't in
    `settings.admin_user_ids`, `404` if the resolved user doesn't exist.
    Callers do::

        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner
    """
    telegram_id = request[TELEGRAM_USER_KEY].get('id')
    user_repo = UserRepository(session)
    caller = await user_repo.get_by_telegram_id(telegram_id) if telegram_id else None

    if not param_user:
        if not caller:
            return web.json_response({'error': 'User not found'}, status=404)
        return caller

    is_self = bool(caller and caller.username == param_user)
    if not is_self and telegram_id not in settings.admin_user_ids:
        return web.json_response({'error': 'Forbidden'}, status=403)

    owner = await user_repo.get_by_username(param_user)
    if not owner:
        return web.json_response({'error': 'User not found'}, status=404)
    return owner


def _aggregate_volume(
    sessions: list, muscle_filter: str | None = None
) -> tuple[list[dict], list[dict], float]:
    """Aggregate a list of completed ``WorkoutSession`` (sets eagerly
    loaded) into ``(by_day, by_muscle, total_volume)`` — shared by GYM-4's
    volume breakdown and GYM-6's activity summary (`most_trained_muscle`).

    ``by_day`` groups volume by local calendar date (``settings.timezone``);
    ``by_muscle`` is sorted by volume descending. When ``muscle_filter`` is
    set, only sets in that muscle group count.
    """
    by_day: dict[str, float] = {}
    by_muscle: dict[str, dict] = {}
    total_volume = 0.0

    for workout_session in sessions:
        for workout_set in workout_session.sets:
            muscle = workout_set.muscle_group or 'Інше'
            if muscle_filter and muscle != muscle_filter:
                continue

            volume = workout_set.weight * workout_set.reps
            total_volume += volume

            day_key = to_local_date(
                workout_set.performed_at, settings.timezone
            ).isoformat()
            by_day[day_key] = by_day.get(day_key, 0.0) + volume

            bucket = by_muscle.setdefault(
                muscle, {'volume': 0.0, 'sets_count': 0}
            )
            bucket['volume'] += volume
            bucket['sets_count'] += 1

    by_day_list = [
        {'date': date_str, 'volume': volume}
        for date_str, volume in sorted(by_day.items())
    ]
    by_muscle_list = [
        {
            'muscle_group': muscle,
            'volume': bucket['volume'],
            'sets_count': bucket['sets_count'],
        }
        for muscle, bucket in sorted(
            by_muscle.items(), key=lambda item: item[1]['volume'], reverse=True
        )
    ]
    return by_day_list, by_muscle_list, total_volume


@webapp_auth
async def api_get_volume_statistics(request: web.Request) -> web.Response:
    """API endpoint (GYM-4): workout volume (weight × reps) over a period,
    grouped by day and by muscle group.

    Query params: `period=week|month|all` (default `week`), `muscle`
    (optional exact muscle-group filter — when set, `by_muscle` has a
    single element and `by_day` reflects only that group), `user` (optional
    username, for a trainer viewing a client's stats — same convention as
    `/workout`; defaults to the caller's own `telegram_id`).
    Expects Authorization header with Telegram initData.
    """
    period = request.query.get('period', 'week')
    if period not in _VALID_STATISTICS_PERIODS:
        return web.json_response(
            {'error': "Invalid period: must be 'week', 'month' or 'all'"},
            status=400,
        )
    muscle_filter = request.query.get('muscle') or None
    param_user = request.query.get('user') or None

    async with async_session_maker() as session:
        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner

        start, end = period_bounds_utc(period, settings.timezone)
        sessions = await WorkoutSessionRepository(session).get_sessions_by_period(
            owner.id, start=start, end=end
        )

    by_day, by_muscle, total_volume = _aggregate_volume(sessions, muscle_filter)

    return web.json_response({
        'success': True,
        'data': {
            'by_day': by_day,
            'by_muscle': by_muscle,
            'total_volume': total_volume,
        },
    })


@webapp_auth
async def api_get_statistics_summary(request: web.Request) -> web.Response:
    """API endpoint (GYM-6): overall activity summary for a period —
    workout count, average duration, total volume and the most-trained
    muscle group. One completed ``WorkoutSession`` = one workout.

    Query params: `period=week|month|all` (default `week`), `user`
    (optional username, trainer viewing a client's stats — same convention
    as `/workout` and `/api/statistics/volume`).
    Expects Authorization header with Telegram initData.
    """
    period = request.query.get('period', 'week')
    if period not in _VALID_STATISTICS_PERIODS:
        return web.json_response(
            {'error': "Invalid period: must be 'week', 'month' or 'all'"},
            status=400,
        )
    param_user = request.query.get('user') or None

    async with async_session_maker() as session:
        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner

        start, end = period_bounds_utc(period, settings.timezone)
        sessions = await WorkoutSessionRepository(session).get_sessions_by_period(
            owner.id, start=start, end=end
        )

    durations = [
        s.duration_seconds for s in sessions if s.duration_seconds is not None
    ]
    avg_duration_minutes = (
        round(sum(durations) / len(durations) / 60, 1) if durations else 0
    )

    _, by_muscle, total_volume = _aggregate_volume(sessions)
    most_trained_muscle = by_muscle[0]['muscle_group'] if by_muscle else None

    return web.json_response({
        'success': True,
        'data': {
            'workouts_count': len(sessions),
            'avg_duration_minutes': avg_duration_minutes,
            'total_volume': total_volume,
            'most_trained_muscle': most_trained_muscle,
        },
    })


@webapp_auth
async def api_get_exercises(request: web.Request) -> web.Response:
    """API endpoint (GYM-5a): the caller's distinct logged exercises, each
    with its (most recent) muscle group — for an exercise picker (GYM-5b).

    Query params: `user` (optional username, trainer viewing a client's
    stats — same convention as `/api/statistics/volume`).
    Expects Authorization header with Telegram initData.
    """
    param_user = request.query.get('user') or None

    async with async_session_maker() as session:
        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner

        exercises = await WorkoutSetRepository(session).get_distinct_exercises(
            owner.id
        )

    return web.json_response({'success': True, 'data': exercises})


@webapp_auth
async def api_get_exercise_progress(request: web.Request) -> web.Response:
    """API endpoint (GYM-5a): how one exercise's working weight/reps
    changed over time — one entry per *session* the exercise appears in,
    oldest first.

    Query params: `exercise` (required, exact name), `user` (optional
    username, trainer viewing a client's stats — same convention as
    `/api/statistics/volume`).
    Expects Authorization header with Telegram initData.
    """
    exercise_name = request.query.get('exercise') or None
    if not exercise_name:
        return web.json_response(
            {'error': 'Missing required param: exercise'}, status=400
        )
    param_user = request.query.get('user') or None

    async with async_session_maker() as session:
        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner

        sets = await WorkoutSetRepository(session).get_sets_by_user_and_exercise(
            owner.id, exercise_name
        )

    # Group the (already date-ascending) flat set list by session — a
    # session normally logs an exercise once, but grouping (rather than
    # assuming one row per session) is correct either way.
    sessions_order: list[int] = []
    by_session: dict[int, list] = {}
    for workout_set in sets:
        if workout_set.session_id not in by_session:
            sessions_order.append(workout_set.session_id)
            by_session[workout_set.session_id] = []
        by_session[workout_set.session_id].append(workout_set)

    progress = []
    for session_id in sessions_order:
        session_sets = by_session[session_id]
        top_set = max(session_sets, key=lambda s: (s.weight, s.reps))
        progress.append({
            'date': to_local_date(
                session_sets[0].performed_at, settings.timezone
            ).isoformat(),
            'max_weight': max(s.weight for s in session_sets),
            'total_reps': sum(s.reps for s in session_sets),
            'total_volume': sum(s.weight * s.reps for s in session_sets),
            'top_set': {'weight': top_set.weight, 'reps': top_set.reps},
        })

    return web.json_response({'success': True, 'data': progress})


def _serialize_pr_value(value, tz_name: str) -> dict:
    """A ``SetRecord``/``EstimatedOneRepMaxRecord`` (GYM-7) as JSON, with
    ``achieved_at`` as a local calendar date (`settings.timezone`), same
    convention as the other `/api/statistics/*` endpoints.
    """
    data = {
        'weight': value.weight,
        'reps': value.reps,
        'achieved_at': to_local_date(value.achieved_at, tz_name).isoformat(),
    }
    if hasattr(value, 'estimated_1rm'):
        data['estimated_1rm'] = round(value.estimated_1rm, 1)
    return data


@webapp_auth
async def api_get_records(request: web.Request) -> web.Response:
    """API endpoint (GYM-8): each exercise's current personal records
    (GYM-7) — heaviest weight, most reps in a single set, and best
    estimated 1RM, each with its own ``achieved_at``, plus a top-level
    ``achieved_at`` (the most recent of the three) driving the "fresh PR"
    highlight in the UI. Sorted by muscle group, then exercise name.

    Query params: `user` (optional username, trainer viewing a client's
    stats — same convention as `/api/statistics/volume`).
    Expects Authorization header with Telegram initData.
    """
    param_user = request.query.get('user') or None

    async with async_session_maker() as session:
        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner

        sessions = await WorkoutSessionRepository(session).get_sessions_by_period(
            owner.id
        )

    all_sets = [workout_set for wsession in sessions for workout_set in wsession.sets]
    prs = calculate_prs(all_sets)

    records = []
    for pr in prs.values():
        max_weight = _serialize_pr_value(pr.max_weight, settings.timezone)
        max_reps = _serialize_pr_value(pr.max_reps, settings.timezone)
        estimated_1rm = _serialize_pr_value(pr.estimated_1rm, settings.timezone)

        records.append({
            'exercise': pr.exercise_name,
            'muscle_group': pr.muscle_group,
            'max_weight': max_weight,
            'max_reps': max_reps,
            'estimated_1rm': estimated_1rm,
            # ISO date strings sort correctly as strings.
            'achieved_at': max(
                max_weight['achieved_at'],
                max_reps['achieved_at'],
                estimated_1rm['achieved_at'],
            ),
        })

    records.sort(key=lambda r: (r['muscle_group'] or '', r['exercise']))

    return web.json_response({'success': True, 'data': records})


@webapp_auth
async def api_get_streak(request: web.Request) -> web.Response:
    """API endpoint (GYM-12): how many consecutive ISO weeks (Monday-Sunday,
    `settings.timezone`) had at least one completed workout, ending at the
    current week — see `calculate_streak` for exactly how the current,
    still-incomplete week is handled so it doesn't falsely break a streak.

    Query params: `user` (optional username, trainer viewing a client's
    streak — same convention as `/api/statistics/volume`).
    Expects Authorization header with Telegram initData.
    """
    param_user = request.query.get('user') or None

    async with async_session_maker() as session:
        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner

        sessions = await WorkoutSessionRepository(session).get_sessions_by_period(
            owner.id
        )

    session_dates = [
        to_local_date(s.performed_at, settings.timezone) for s in sessions
    ]
    today = to_local_date(utcnow(), settings.timezone)
    data = calculate_streak(session_dates, today)

    return web.json_response({'success': True, 'data': data})


@webapp_auth
async def api_get_achievements(request: web.Request) -> web.Response:
    """API endpoint (GYM-13b): every achievement in the fixed catalog
    (GYM-13a's `ACHIEVEMENTS`), each flagged whether the caller (or
    `?user=` client) has unlocked it and when — the "Досягнення" tab
    renders unlocked ones in color and locked ones greyed out with
    `description` as the hint. Catalog order (unlike GYM-8's records,
    there's no "which is most interesting" sort here).

    Query params: `user` (optional username, trainer viewing a client's
    achievements — same convention as `/api/statistics/volume`).
    Expects Authorization header with Telegram initData.
    """
    param_user = request.query.get('user') or None

    async with async_session_maker() as session:
        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner

        unlocked_at_by_code = await UserAchievementRepository(
            session
        ).get_unlocked_at_by_code(owner.id)

    data = [
        {
            'code': achievement.code,
            'title': achievement.title,
            'description': achievement.description,
            'unlocked': achievement.code in unlocked_at_by_code,
            'unlocked_at': (
                to_local_date(
                    unlocked_at_by_code[achievement.code], settings.timezone
                ).isoformat()
                if achievement.code in unlocked_at_by_code else None
            ),
        }
        for achievement in ACHIEVEMENTS
    ]

    return web.json_response({'success': True, 'data': data})


@webapp_auth
async def api_get_workout_program(request: web.Request) -> web.Response:
    """API endpoint to get workout program exercises for a session.

    DB is the primary store (GYM-28) — Sheets is no longer read here.
    Response shape is unchanged (`{"data": {"exercises": [...]}}`, each
    row in `WorkoutProgramRepository.get_program`'s Sheets-compatible
    form), so `workout.html`/`nutrition.html` needed no changes.

    Query params: `user` (optional — defaults to the caller; a trainer
    passing someone else's requires `settings.admin_user_ids`, GYM-28),
    `day` (optional), `muscle` (optional).
    Expects Authorization header with Telegram initData.
    """
    param_user = request.query.get('user') or None
    day_str = request.query.get('day', '')
    muscle = request.query.get('muscle') or None
    day = int(day_str) if day_str and day_str.isdigit() else None

    async with async_session_maker() as session:
        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner

        programs = await WorkoutProgramRepository(session).get_program(
            owner.id, day=day, muscle=muscle
        )

    return web.json_response({
        'success': True,
        'data': {
            'exercises': programs,
        },
    })


@webapp_auth
async def api_add_program_exercise(request: web.Request) -> web.Response:
    """API endpoint (GYM-30) to add one exercise to a workout program day
    from the Mini App — the webapp-side counterpart to the bot's
    program-creation FSM (``src/bot/handlers/workout_program.py``).

    Body: ``{user?, day, muscle_group, exercise, sets_reps, comment?}``.
    ``sets_reps`` is validated with the same rule the bot FSM uses
    (:func:`src.services.workout_program_parsing.is_valid_sets_reps`),
    ``muscle_group`` must be one of ``MUSCLE_GROUPS``. DB is the primary
    store (GYM-28); the addition is also mirrored to Sheets — non-
    critically, logged on failure only — when the owner has
    ``sync_workout_to_sheets`` enabled, same convention as
    ``api_delete_workout_day``/the bot's ``program:finish``.

    Response: the newly added row, in the same shape as one entry of
    ``GET /api/workout/program``'s ``data.exercises``.
    Expects Authorization header with Telegram initData.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({'error': 'Invalid JSON'}, status=400)

    day_raw = body.get('day')
    muscle_group = (body.get('muscle_group') or '').strip()
    exercise_name = (body.get('exercise') or '').strip()
    sets_reps = (body.get('sets_reps') or '').strip()
    comment = (body.get('comment') or '').strip()
    param_user = body.get('user') or None

    if not isinstance(day_raw, int) or isinstance(day_raw, bool) or day_raw < 1:
        return web.json_response(
            {'error': 'Missing or invalid required field: day'}, status=400
        )
    if muscle_group not in MUSCLE_GROUPS:
        return web.json_response(
            {'error': 'Missing or invalid required field: muscle_group'}, status=400
        )
    if not exercise_name:
        return web.json_response(
            {'error': 'Missing required field: exercise'}, status=400
        )
    if not sets_reps or not is_valid_sets_reps(sets_reps):
        return web.json_response(
            {'error': 'Missing or invalid required field: sets_reps'}, status=400
        )

    item = {
        'exercise': exercise_name,
        'muscle_group': muscle_group,
        'sets_reps': sets_reps,
        'comment': comment,
    }

    async with async_session_maker() as session:
        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner

        created_rows = await WorkoutProgramRepository(session).add_exercises(
            owner.id, day_raw, [item]
        )
        await session.commit()
        row = created_rows[0]
        # GYM-31: exercise_id/has_details, same as GET /api/workout/program
        # — fetched explicitly rather than via the row's lazy `exercise`
        # relationship, which isn't awaitable under async SQLAlchemy.
        catalog_exercise = await ExerciseRepository(session).get_by_id(
            row.exercise_id
        )
        response_row = {
            'day': str(row.day),
            'muscle_group': row.muscle_group,
            'exercise': row.exercise_name,
            'sets_reps': row.sets_reps,
            'comment': row.comment or '',
            'created_at': row.created_at.strftime('%d.%m.%Y %H:%M'),
            'exercise_id': row.exercise_id,
            'has_details': bool(
                catalog_exercise
                and (
                    catalog_exercise.description
                    or catalog_exercise.image_url
                    or catalog_exercise.video_url
                )
            ),
        }

        sync_enabled = owner.sync_workout_to_sheets
        owner_username = owner.username

    if sync_enabled and owner_username:
        try:
            sheets_service = GoogleSheetsService()
            await sheets_service.add_workout_program(
                [{**item, 'day': day_raw}], user_name=owner_username
            )
        except Exception as e:
            logger.warning(f'Failed to mirror new exercise to Sheets: {e}')

    return web.json_response({'success': True, 'data': response_row})


@webapp_auth
async def api_search_exercises(request: web.Request) -> web.Response:
    """API endpoint (GYM-30): autocomplete search over the shared
    ``Exercise`` catalog (GYM-27), for the "add exercise" form's name
    field — so a user typing "жим лёжа" gets prompted with the existing
    "Жим лежачи" entry instead of creating a near-duplicate.

    Query params: `q` (search text; blank returns an empty list — see
    ``ExerciseRepository.search``). No `user`/ownership check — the
    catalog is shared across every user, same as
    ``GET /api/exercises/{id}`` (GYM-31).
    Expects Authorization header with Telegram initData.
    """
    q = request.query.get('q', '')

    async with async_session_maker() as session:
        exercises = await ExerciseRepository(session).search(q, limit=10)

    return web.json_response({
        'success': True,
        'data': [
            {'id': ex.id, 'name': ex.name, 'muscle_group': ex.muscle_group}
            for ex in exercises
        ],
    })


@webapp_auth
async def api_get_exercise(request: web.Request) -> web.Response:
    """API endpoint (GYM-31): one catalog entry's details, for the
    ``/workout`` "ⓘ" bottom sheet (image/video/description).

    No `user`/ownership check — the ``Exercise`` catalog is shared across
    every user, same as ``GET /api/exercises`` (GYM-30).
    Path param: `id` (int). Expects Authorization header with Telegram
    initData.
    """
    id_str = request.match_info.get('id', '')
    if not id_str.isdigit():
        return web.json_response({'error': 'Invalid exercise id'}, status=400)

    async with async_session_maker() as session:
        exercise = await ExerciseRepository(session).get_by_id(int(id_str))

    if exercise is None:
        return web.json_response({'error': 'Exercise not found'}, status=404)

    return web.json_response({
        'success': True,
        'data': {
            'id': exercise.id,
            'name': exercise.name,
            'muscle_group': exercise.muscle_group,
            'description': exercise.description,
            'image_url': exercise.image_url,
            'video_url': exercise.video_url,
        },
    })


async def api_get_last_workout_log(request: web.Request) -> web.Response:
    """API endpoint to get previous workout data for diff display.

    Query params: user, exercises (comma-separated), day (optional).
    Expects Authorization header with Telegram initData.
    """
    init_data = request.headers.get('Authorization', '')
    user_data = validate_telegram_webapp_data(init_data)

    if not user_data:
        return web.json_response({'error': 'Unauthorized'}, status=401)

    user_name = request.query.get('user', '')
    exercises_str = request.query.get('exercises', '')
    day_str = request.query.get('day', '')

    if not user_name or not exercises_str:
        return web.json_response(
            {'error': 'Missing required params: user, exercises'}, status=400
        )

    exercises = [e.strip() for e in exercises_str.split(',') if e.strip()]
    day = int(day_str) if day_str and day_str.isdigit() else None

    try:
        sheets_service = GoogleSheetsService()
        last_logs = await sheets_service.get_last_workout_log(
            user_name, exercises, day
        )

        return web.json_response({
            'success': True,
            'data': last_logs,
        })

    except Exception as e:
        logger.error(f'Error loading last workout log: {e}')
        return web.json_response(
            {'error': 'Failed to load logs'}, status=500
        )


@webapp_auth
async def api_get_sync_settings(request: web.Request) -> web.Response:
    """API endpoint to get the caller's Google Sheets sync preference.

    The database is always the source of truth for workout logs (GYM-2);
    this setting only controls whether logs are *also* mirrored to Sheets.
    Expects Authorization header with Telegram initData.
    """
    telegram_id = request[TELEGRAM_USER_KEY].get('id')
    if not telegram_id:
        return web.json_response({'error': 'Invalid user data'}, status=400)

    async with async_session_maker() as session:
        user = await UserRepository(session).get_by_telegram_id(telegram_id)
        if not user:
            return web.json_response({'error': 'User not found'}, status=404)

        return web.json_response({
            'success': True,
            'data': {'sync_workout_to_sheets': user.sync_workout_to_sheets},
        })


@webapp_auth
async def api_update_sync_settings(request: web.Request) -> web.Response:
    """API endpoint to toggle Google Sheets sync for workout logs.

    Expects Authorization header with Telegram initData.
    Body: { sync_workout_to_sheets: bool }
    """
    telegram_id = request[TELEGRAM_USER_KEY].get('id')
    if not telegram_id:
        return web.json_response({'error': 'Invalid user data'}, status=400)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({'error': 'Invalid JSON'}, status=400)

    enabled = bool(body.get('sync_workout_to_sheets'))

    async with async_session_maker() as session:
        user = await UserRepository(session).set_sync_workout_to_sheets(
            telegram_id, enabled
        )
        if not user:
            return web.json_response({'error': 'User not found'}, status=404)

        await session.commit()

        return web.json_response({
            'success': True,
            'data': {'sync_workout_to_sheets': user.sync_workout_to_sheets},
        })


@webapp_auth
async def api_start_workout_session(request: web.Request) -> web.Response:
    """API endpoint to start or resume an in-progress workout session.

    The DB is the source of truth for the in-progress log, not just the
    finished one (GYM-2c): called when the WebApp opens, this returns an
    existing unfinished session for (user, day, muscle) if one was started
    within the last 24h, or creates a fresh one. The WebApp uses the
    response to restore already-logged sets instead of (or in addition to)
    its ``localStorage`` cache.

    Expects Authorization header with Telegram initData.
    Body: { user, day, muscle }
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({'error': 'Invalid JSON'}, status=400)

    user_name = body.get('user', '')
    day = body.get('day', '')
    muscle = body.get('muscle', '')

    if not user_name:
        return web.json_response(
            {'error': 'Missing required field: user'}, status=400
        )

    day_int = int(day) if str(day).isdigit() else None
    muscle_norm = muscle or None

    async with async_session_maker() as session:
        owner = await UserRepository(session).get_by_username(user_name)
        if not owner:
            return web.json_response({'error': 'User not found'}, status=404)

        session_repo = WorkoutSessionRepository(session)
        draft = await session_repo.get_active_draft(
            owner.id, day=day_int, muscle_group=muscle_norm
        )
        resumed = draft is not None
        if draft is None:
            draft = await session_repo.start_draft_session(
                owner.id, day=day_int, muscle_group=muscle_norm
            )
        await session.commit()

        sets_by_exercise: dict[str, list[dict]] = {}
        if resumed:
            for workout_set in sorted(draft.sets, key=lambda s: s.set_number):
                sets_by_exercise.setdefault(workout_set.exercise_name, []).append({
                    'set': workout_set.set_number,
                    'weight': workout_set.weight,
                    'reps': workout_set.reps,
                })

        from datetime import timezone

        started_at_ms = int(
            draft.performed_at.replace(tzinfo=timezone.utc).timestamp() * 1000
        )

        return web.json_response({
            'success': True,
            'data': {
                'session_id': draft.id,
                'resumed': resumed,
                'started_at_ms': started_at_ms,
                'sets_by_exercise': sets_by_exercise,
            },
        })


@webapp_auth
async def api_sync_workout_session_exercise(request: web.Request) -> web.Response:
    """API endpoint to autosave one exercise's sets within a draft session.

    Called after every add/edit/remove of a set while the workout is in
    progress (GYM-2c), so the DB reflects the log without waiting for
    "Завершити тренування". Replaces *all* of the exercise's sets in one
    call (see ``WorkoutSetRepository.replace_exercise_sets``).

    Expects Authorization header with Telegram initData.
    Body: { session_id, exercise, muscle_group, planned_sets_reps,
            sets: [{ set, weight, reps }] }
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({'error': 'Invalid JSON'}, status=400)

    session_id = body.get('session_id')
    exercise_name = body.get('exercise', '')
    muscle_group = body.get('muscle_group') or None
    planned_sets_reps = body.get('planned_sets_reps') or None
    raw_sets = body.get('sets', [])

    if not session_id or not exercise_name:
        return web.json_response(
            {'error': 'Missing required fields: session_id, exercise'},
            status=400,
        )

    # Skip incomplete sets (empty weight/reps), same as api_save_workout_log.
    sets = [
        {
            'set_number': s.get('set'),
            'weight': float(s.get('weight')),
            'reps': int(s.get('reps')),
        }
        for s in raw_sets
        if s.get('weight', '') and s.get('reps', '')
    ]

    async with async_session_maker() as session:
        workout_session = await WorkoutSessionRepository(session).get_by_id(
            session_id
        )

        if workout_session is None:
            return web.json_response({'error': 'Session not found'}, status=404)
        if workout_session.completed_at is not None:
            return web.json_response(
                {'error': 'Session already completed'}, status=409
            )

        await WorkoutSetRepository(session).replace_exercise_sets(
            session_id=session_id,
            user_id=workout_session.user_id,
            exercise_name=exercise_name,
            muscle_group=muscle_group,
            planned_sets_reps=planned_sets_reps,
            sets=sets,
            performed_at=workout_session.performed_at,
        )
        await session.commit()

    return web.json_response({'success': True})


async def api_save_workout_log(request: web.Request) -> web.Response:
    """API endpoint to save a completed workout log.

    Expects Authorization header with Telegram initData.
    Body: { user, day, exercises: [{ exercise, muscle_group,
            planned_sets_reps, sets: [{ set, weight, reps }] }] }

    The database is the source of truth (GYM-2): the session and its sets
    are saved there first, and that write must succeed for the request to
    succeed. If a draft session for (user, day, muscle) already exists
    (started via ``/api/workout/session/start``, GYM-2c), it is reconciled
    to match this body and marked completed; otherwise a fresh session is
    created atomically (older client, or the draft never got created).
    Google Sheets is written to afterwards, and only if the workout's owner
    opted in via ``/api/user/sync-settings``; a Sheets failure is logged but
    never fails the request (the DB copy already exists).
    """
    init_data = request.headers.get('Authorization', '')
    user_data = validate_telegram_webapp_data(init_data)

    if not user_data:
        return web.json_response({'error': 'Unauthorized'}, status=401)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({'error': 'Invalid JSON'}, status=400)

    user_name = body.get('user', '')
    day = body.get('day', '')
    muscle = body.get('muscle', '')
    duration_seconds = body.get('duration_seconds', 0)
    exercises = body.get('exercises', [])

    if not user_name or not exercises:
        return web.json_response(
            {'error': 'Missing required fields: user, exercises'}, status=400
        )

    # `now` drives the Sheets row / calendar event, same as before
    # (server-local time). `performed_at` is the UTC timestamp stored on
    # the DB session, per GYM-2.
    now = datetime.now()
    performed_at = utcnow()
    date_str = now.strftime('%d.%m.%Y')
    timestamp_str = now.strftime('%d.%m.%Y %H:%M')
    day_int = int(day) if str(day).isdigit() else None

    log_entries = []
    db_sets = []
    # Per-exercise view of the same data, for reconciling a draft session
    # (GYM-2c): {exercise_name: {muscle_group, planned_sets_reps, sets}}.
    exercise_meta: dict[str, dict] = {}
    for ex in exercises:
        exercise_name = ex.get('exercise', '')
        muscle_group_ex = ex.get('muscle_group') or None
        planned = ex.get('planned_sets_reps') or None
        meta = exercise_meta.setdefault(
            exercise_name,
            {'muscle_group': muscle_group_ex, 'planned_sets_reps': planned, 'sets': []},
        )

        for s in ex.get('sets', []):
            weight = s.get('weight', '')
            reps = s.get('reps', '')

            log_entries.append({
                'date': date_str,
                'exercise': exercise_name,
                'muscle_group': ex.get('muscle_group', ''),
                'day': day,
                'set_number': s.get('set', ''),
                'weight': weight,
                'reps': reps,
                'planned_sets_reps': ex.get('planned_sets_reps', ''),
                'timestamp': timestamp_str,
            })

            # Skip incomplete sets (empty weight/reps), same as
            # GoogleSheetsService.get_last_workout_log.
            if not weight or not reps:
                continue

            set_row = {
                'exercise_name': exercise_name,
                'muscle_group': muscle_group_ex,
                'set_number': s.get('set'),
                'weight': float(weight),
                'reps': int(reps),
                'planned_sets_reps': planned,
            }
            db_sets.append(set_row)
            meta['sets'].append({
                'set_number': set_row['set_number'],
                'weight': set_row['weight'],
                'reps': set_row['reps'],
            })

    async with async_session_maker() as session:
        owner = await UserRepository(session).get_by_username(user_name)
        if not owner:
            return web.json_response({'error': 'User not found'}, status=404)

        session_repo = WorkoutSessionRepository(session)
        muscle_norm = muscle or None

        try:
            draft = await session_repo.get_active_draft(
                owner.id, day=day_int, muscle_group=muscle_norm
            )
            if draft is not None:
                set_repo = WorkoutSetRepository(session)
                for exercise_name, meta in exercise_meta.items():
                    await set_repo.replace_exercise_sets(
                        session_id=draft.id,
                        user_id=owner.id,
                        exercise_name=exercise_name,
                        muscle_group=meta['muscle_group'],
                        planned_sets_reps=meta['planned_sets_reps'],
                        sets=meta['sets'],
                        performed_at=draft.performed_at,
                    )
                await session_repo.complete_session(
                    draft.id,
                    owner.id,
                    duration_seconds=duration_seconds,
                    day=day_int,
                    muscle_group=muscle_norm,
                )
                session_performed_at = draft.performed_at
            else:
                # No draft (older client, or /session/start was never
                # called) — fall back to the original one-shot save.
                await session_repo.create_session_with_sets(
                    user_id=owner.id,
                    performed_at=performed_at,
                    day=day_int,
                    muscle_group=muscle_norm,
                    duration_seconds=duration_seconds,
                    sets=db_sets,
                )
                session_performed_at = performed_at
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f'Error saving workout to DB: {e}')
            return web.json_response(
                {'error': 'Failed to save workout'}, status=500
            )

        owner_id = owner.id
        owner_telegram_id = owner.telegram_id
        sync_to_sheets = owner.sync_workout_to_sheets

    # (GYM-47) The workout is now durably saved in the DB — cancel any
    # still-pending rest-timer reminder for the *caller* (not necessarily
    # `owner`: a trainer may be saving on a client's behalf, but it's the
    # caller's own device that started the timer and would receive the
    # notification). Closes the common case where the last set's rest
    # timer is still running when "Завершити тренування" is tapped.
    caller_telegram_id = user_data.get('id')
    if caller_telegram_id:
        _cancel_rest_timer(caller_telegram_id)

    # Optional Sheets mirror, opt-in via settings. Never fails the request:
    # the workout is already durably saved in the DB above.
    synced_to_sheets = False
    if sync_to_sheets:
        try:
            sheets_service = GoogleSheetsService()
            synced_to_sheets = await sheets_service.save_workout_log(
                user_name, log_entries
            )
            if not synced_to_sheets:
                logger.warning(
                    f'Google Sheets sync returned false for {user_name} '
                    '(non-critical, workout already saved to DB)'
                )
        except Exception as sheets_err:
            logger.warning(f'Google Sheets sync failed (non-critical): {sheets_err}')

    # Sync workout to Google Calendar
    try:
        await _sync_workout_to_calendar(
            user_name, day, muscle, exercises,
            duration_seconds, now,
        )
    except Exception as cal_err:
        logger.warning(f'Calendar sync failed (non-critical): {cal_err}')

    # Notify the workout's owner of any PR this session just set (GYM-9).
    try:
        await _notify_new_prs(
            owner_id, owner_telegram_id, session_performed_at,
            set(exercise_meta.keys()),
        )
    except Exception as pr_err:
        logger.warning(f'PR notification failed (non-critical): {pr_err}')

    # Unlock any achievement this session's updated history now satisfies
    # (GYM-13a), notifying the owner about anything newly earned.
    try:
        await _check_and_unlock_achievements(owner_id, owner_telegram_id)
    except Exception as achievement_err:
        logger.warning(f'Achievement check failed (non-critical): {achievement_err}')

    return web.json_response({
        'success': True,
        'synced_to_sheets': synced_to_sheets,
    })


async def api_start_rest_timer(request: web.Request) -> web.Response:
    """API endpoint to start rest timer and send notification after 60 seconds.

    Expects Authorization header with Telegram initData.
    Body: { duration_seconds: 60, session_id?, user?, day?, muscle? }

    GYM-47: an optional ``session_id`` (the draft workout session this
    timer belongs to, GYM-2c) lets the scheduled reminder check — right
    before it would fire — whether that workout has since been completed
    (see :func:`src.services.rest_timer.should_send_rest_reminder`) and
    skip sending if so; omitted, the reminder still sends unconditionally
    like before (older client, or no session to check against). Starting a
    new timer also cancels this caller's previous still-pending one, if
    any — the client only ever runs one at a time, so an old one left over
    is stale.
    """
    init_data = request.headers.get('Authorization', '')
    user_data = validate_telegram_webapp_data(init_data)

    if not user_data:
        return web.json_response({'error': 'Unauthorized'}, status=401)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({'error': 'Invalid JSON'}, status=400)

    duration_seconds = body.get('duration_seconds', 60)
    telegram_user_id = user_data.get('id')
    workout_user = body.get('user', '')
    workout_day = body.get('day', '')
    workout_muscle = body.get('muscle', '')
    session_id = body.get('session_id')
    if not isinstance(session_id, int):
        session_id = None

    if not telegram_user_id:
        return web.json_response(
            {'error': 'Missing telegram user id'}, status=400
        )

    # Log received parameters for debugging
    logger.info(
        f"Rest timer request: user={workout_user}, "
        f"day={workout_day}, muscle={workout_muscle}"
    )

    # A fresh timer replaces whatever this caller's previous one was still
    # waiting on (GYM-47).
    _cancel_rest_timer(telegram_user_id)

    # Schedule notification using bot
    try:
        from aiogram.types import (
            InlineKeyboardMarkup,
            InlineKeyboardButton,
            WebAppInfo,
        )

        bot = get_bot_instance()
        if not bot:
            return web.json_response(
                {'error': 'Bot instance not available'}, status=503
            )

        async def send_delayed_notification():
            await asyncio.sleep(duration_seconds)
            try:
                if session_id is not None:
                    async with async_session_maker() as check_session:
                        workout_session = await WorkoutSessionRepository(
                            check_session
                        ).get_by_id(session_id)
                    if not should_send_rest_reminder(workout_session):
                        logger.debug(
                            f'Rest timer reminder for session {session_id} '
                            'skipped: workout already completed'
                        )
                        return

                # Build WebApp URL with parameters (URL-encoded)
                from urllib.parse import urlencode

                params = {'user': workout_user, 'day': workout_day}
                if workout_muscle:  # Only add muscle if not empty
                    params['muscle'] = workout_muscle

                webapp_url = (
                    f"{settings.webapp_url}/workout?{urlencode(params)}"
                )

                logger.info(
                    f"Sending rest timer notification with URL: {webapp_url}"
                )

                # Create inline keyboard with button to return to workout
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="🏋️ Повернутися до тренування",
                                web_app=WebAppInfo(url=webapp_url)
                            )
                        ]
                    ]
                )

                await bot.send_message(
                    telegram_user_id,
                    '⏱️ *Час відпочинку закінчився!*\n\n'
                    'Готові до наступного підходу? 💪',
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f'Failed to send rest timer notification: {e}')
            finally:
                # Self-cleanup (GYM-47): only remove this task's own
                # registry entry — if a newer timer already replaced it
                # (via `_cancel_rest_timer` above), leave that one alone.
                if _rest_timer_tasks.get(telegram_user_id) is asyncio.current_task():
                    _rest_timer_tasks.pop(telegram_user_id, None)

        # Start task in background
        task = asyncio.create_task(send_delayed_notification())
        _rest_timer_tasks[telegram_user_id] = task

        return web.json_response({
            'success': True,
            'message': f'Notification scheduled in {duration_seconds}s'
        })

    except Exception as e:
        logger.error(f'Error scheduling rest timer notification: {e}')
        return web.json_response(
            {'error': 'Failed to schedule notification'}, status=500
        )


@webapp_auth
async def api_cancel_rest_timer(request: web.Request) -> web.Response:
    """API endpoint (GYM-47) to cancel the caller's pending rest-timer
    reminder — used when they tap the timer to stop it manually
    (`workout.html`'s rest-timer click handler).

    Idempotent: always `200`, whether or not a timer was actually pending
    — "no timer running" is a normal outcome here, not an error.
    Expects Authorization header with Telegram initData.
    """
    telegram_user_id = request[TELEGRAM_USER_KEY].get('id')
    if telegram_user_id:
        _cancel_rest_timer(telegram_user_id)
    return web.json_response({'success': True})


@webapp_auth
async def api_delete_workout_day(request: web.Request) -> web.Response:
    """API endpoint to delete a workout program day, or (GYM-41) just one
    muscle group within it.

    DB is the primary store (GYM-28); the deletion is also mirrored to
    Sheets — non-critically, logged on failure only — when the owner has
    `sync_workout_to_sheets` enabled.

    Query params: `user` (optional — defaults to the caller; someone
    else's requires `settings.admin_user_ids`, GYM-28), `day` (required),
    `muscle` (optional — GYM-41: a day can span several muscle groups
    since GYM-30, so scoping the delete to one avoids silently taking the
    others with it; omitted, this deletes the whole day, unchanged from
    before GYM-41).
    Expects Authorization header with Telegram initData.
    """
    param_user = request.query.get('user') or None
    day_str = request.query.get('day', '')
    muscle = request.query.get('muscle') or None

    if not day_str or not day_str.isdigit():
        return web.json_response(
            {'error': 'Missing or invalid required param: day'}, status=400
        )
    day = int(day_str)

    async with async_session_maker() as session:
        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner

        program_repo = WorkoutProgramRepository(session)
        # Sheets has no muscle-scoped "delete this day" call — when
        # narrowing to one group, mirror it as one delete_exercise() per
        # affected row instead of the blanket delete_workout_day() below,
        # so Sheets doesn't lose the *other* groups' rows the DB kept.
        exercise_names_for_sheets_mirror = (
            [row['exercise'] for row in await program_repo.get_program(
                owner.id, day=day, muscle=muscle,
            )]
            if muscle
            else []
        )

        deleted = await program_repo.delete_day(owner.id, day, muscle=muscle)
        if not deleted:
            return web.json_response({'error': 'Day not found'}, status=404)
        await session.commit()

        sync_enabled = owner.sync_workout_to_sheets
        owner_username = owner.username

    if sync_enabled and owner_username:
        try:
            sheets_service = GoogleSheetsService()
            if muscle:
                for exercise_name in exercise_names_for_sheets_mirror:
                    await sheets_service.delete_exercise(
                        owner_username, str(day), exercise_name
                    )
            else:
                await sheets_service.delete_workout_day(owner_username, str(day))
        except Exception as e:
            logger.warning(f'Failed to mirror day deletion to Sheets: {e}')

    return web.json_response({'success': True})


@webapp_auth
async def api_delete_exercise(request: web.Request) -> web.Response:
    """API endpoint to delete one exercise from a workout program day.

    DB is the primary store (GYM-28); the deletion is also mirrored to
    Sheets — non-critically, logged on failure only — when the owner has
    `sync_workout_to_sheets` enabled.

    Query params: `user` (optional — defaults to the caller; someone
    else's requires `settings.admin_user_ids`, GYM-28), `day`, `exercise`
    (both required).
    Expects Authorization header with Telegram initData.
    """
    param_user = request.query.get('user') or None
    day_str = request.query.get('day', '')
    exercise = request.query.get('exercise', '')

    if not day_str or not day_str.isdigit() or not exercise:
        return web.json_response(
            {'error': 'Missing or invalid required params: day, exercise'},
            status=400,
        )
    day = int(day_str)

    async with async_session_maker() as session:
        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner

        deleted = await WorkoutProgramRepository(session).delete_exercise(
            owner.id, day, exercise
        )
        if not deleted:
            return web.json_response({'error': 'Exercise not found'}, status=404)
        await session.commit()

        sync_enabled = owner.sync_workout_to_sheets
        owner_username = owner.username

    if sync_enabled and owner_username:
        try:
            sheets_service = GoogleSheetsService()
            await sheets_service.delete_exercise(owner_username, str(day), exercise)
        except Exception as e:
            logger.warning(f'Failed to mirror exercise deletion to Sheets: {e}')

    return web.json_response({'success': True})


async def _sync_workout_to_calendar(
    user_name: str,
    day: str,
    muscle: str,
    exercises: list,
    duration_seconds: int,
    workout_time,
) -> None:
    """Sync completed workout to Google Calendar as a past event.

    Creates a calendar event for the workout that was just completed.
    Non-critical: failures are logged but do not affect workout saving.

    Args:
        user_name: Username for the event title
        day: Program day number
        muscle: Muscle group name
        exercises: List of exercise dicts with sets data
        duration_seconds: Total workout duration in seconds
        workout_time: datetime when workout was saved
    """
    from datetime import timedelta

    calendar_service = GoogleCalendarService()

    if not calendar_service.calendar_id:
        return

    duration_minutes = max(duration_seconds // 60, 1)
    start_time = workout_time - timedelta(seconds=duration_seconds)

    # Build workout summary
    total_sets = sum(len(ex.get('sets', [])) for ex in exercises)
    title_parts = [f'{user_name}']
    if muscle:
        title_parts.append(muscle)
    elif day:
        title_parts.append(f'День {day}')

    summary = f'🏋️ {" — ".join(title_parts)}'

    # Build description with exercise details
    description_lines = [
        f'Тривалість: {duration_minutes} хв',
        f'Вправ: {len(exercises)}, Підходів: {total_sets}',
        '',
    ]
    for ex in exercises:
        sets = ex.get('sets', [])
        sets_info = ', '.join(
            f'{s.get("weight", "?")}x{s.get("reps", "?")}'
            for s in sets
        )
        description_lines.append(f'• {ex.get("exercise", "")} — {sets_info}')

    description = '\n'.join(description_lines)

    import asyncio

    service = calendar_service._get_service()

    event = {
        'summary': summary,
        'description': description,
        'start': {
            'dateTime': start_time.isoformat(),
            'timeZone': settings.timezone,
        },
        'end': {
            'dateTime': workout_time.isoformat(),
            'timeZone': settings.timezone,
        },
    }

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: service.events()
        .insert(calendarId=calendar_service.calendar_id, body=event)
        .execute(),
    )

    logger.info(f'Workout synced to calendar for {user_name}')


async def _notify_new_prs(
    owner_id: uuid.UUID,
    owner_telegram_id: int,
    session_performed_at: datetime,
    exercise_names: set[str],
) -> None:
    """Message the workout's *owner* (GYM-9) for each PR their just-saved
    session set — not whoever opened the WebApp (a trainer logging for a
    client, same distinction as ``api_save_workout_log`` resolving
    ``owner`` from ``body["user"]``).

    Recomputes PRs over the owner's full history via GYM-7's
    ``calculate_prs`` — one query, no "before" snapshot to diff against —
    and treats a PR as new when its ``achieved_at`` equals this session's
    own ``performed_at`` (every set in a session shares that timestamp,
    see ``WorkoutSet.performed_at``). A PR type whose winning set is
    identical to another type's (e.g. the heaviest single also being the
    best estimated 1RM) collapses into a single message. Called from a
    try/except in ``api_save_workout_log``, same as
    ``_sync_workout_to_calendar`` — a failure here must not affect whether
    the workout itself is considered saved.
    """
    bot = get_bot_instance()
    if not bot:
        return

    async with async_session_maker() as session:
        sessions = await WorkoutSessionRepository(session).get_sessions_by_period(
            owner_id
        )

    all_sets = [workout_set for wsession in sessions for workout_set in wsession.sets]
    prs = calculate_prs(all_sets)

    sent: set[tuple[str, float, int]] = set()
    for exercise_name in exercise_names:
        pr = prs.get(exercise_name)
        if pr is None:
            continue

        for pr_value in (pr.max_weight, pr.max_reps, pr.estimated_1rm):
            if pr_value.achieved_at != session_performed_at:
                continue
            key = (exercise_name, pr_value.weight, pr_value.reps)
            if key in sent:
                continue
            sent.add(key)

            await bot.send_message(
                owner_telegram_id,
                f'🏆 Новий рекорд! {exercise_name}: '
                f'{pr_value.weight:g} кг × {pr_value.reps}',
            )


async def _check_and_unlock_achievements(
    owner_id: uuid.UUID, owner_telegram_id: int
) -> None:
    """Unlock any achievement (GYM-13a) the workout owner's updated history
    now satisfies, and message them about each newly-unlocked one.

    Unlike ``_notify_new_prs``, the unlock check (and its DB write) runs
    even when no bot instance is available — an achievement is a
    persisted, permanent row, not just a notification, so it must not be
    skipped merely because there's nothing to message right now. Called
    from a try/except in ``api_save_workout_log``, same non-critical spot
    as ``_notify_new_prs`` (GYM-9) — a failure here must not affect
    whether the workout itself is considered saved.
    """
    async with async_session_maker() as session:
        today = to_local_date(utcnow(), settings.timezone)
        newly_unlocked = await AchievementsService(session).check_and_unlock(
            owner_id, today, settings.timezone
        )
        await session.commit()

    bot = get_bot_instance()
    if not bot:
        return

    for achievement in newly_unlocked:
        await bot.send_message(
            owner_telegram_id,
            f'🏅 Нове досягнення: {achievement.title}',
        )


_DEFAULT_HISTORY_LIMIT = 20
_MAX_HISTORY_LIMIT = 100


def _serialize_session_summary(workout_session) -> dict:
    """One completed ``WorkoutSession`` (sets eagerly loaded) as a history
    list row (GYM-10): counts + total volume + duration, local calendar
    date (`settings.timezone`, same convention as the other
    `/api/statistics/*` endpoints).
    """
    return {
        'session_id': workout_session.id,
        'date': to_local_date(
            workout_session.performed_at, settings.timezone
        ).isoformat(),
        'muscle_group': workout_session.muscle_group,
        'exercises_count': len(
            {s.exercise_name for s in workout_session.sets}
        ),
        'sets_count': len(workout_session.sets),
        'total_volume': sum(
            s.weight * s.reps for s in workout_session.sets
        ),
        'duration_minutes': (
            round(workout_session.duration_seconds / 60, 1)
            if workout_session.duration_seconds is not None
            else 0
        ),
    }


@webapp_auth
async def api_get_today_workout(request: web.Request) -> web.Response:
    """API endpoint (GYM-40): the caller's most recent completed workout
    session for "today" — a short summary for the "Сьогодні" nutrition
    page, so a workout doesn't require a trip to `/statistics` to notice.

    `data` is `null` if there's no completed session today
    (`settings.timezone`); draft sessions (`completed_at IS NULL`) don't
    count, same as everywhere else (GYM-2c). Several sessions on the same
    day are rare (GYM-1 keeps them as separate sessions rather than
    merging) but possible — only the most recent is returned here, the
    rest stay visible via `/statistics` → «Історія».

    Query params: `user` (optional username, trainer viewing a client —
    same convention as the rest of `/api/statistics/*`).
    Expects Authorization header with Telegram initData.
    """
    param_user = request.query.get('user') or None

    async with async_session_maker() as session:
        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner

        start, end = period_bounds_utc('day', settings.timezone)
        sessions = await WorkoutSessionRepository(session).get_sessions_by_period(
            owner.id, start=start, end=end
        )

    data = _serialize_session_summary(sessions[0]) if sessions else None

    return web.json_response({'success': True, 'data': data})


@webapp_auth
async def api_get_history(request: web.Request) -> web.Response:
    """API endpoint (GYM-10): a page of the caller's past *completed*
    workout sessions, most recent first, each with its summary — the
    "Історія" tab list (rendered by GYM-11).

    Query params: `limit` (default 20, max 100), `offset` (default 0),
    `user` (optional username, trainer viewing a client's history — same
    convention as `/api/statistics/volume`).
    Expects Authorization header with Telegram initData.
    """
    try:
        limit = int(request.query.get('limit', _DEFAULT_HISTORY_LIMIT))
        offset = int(request.query.get('offset', 0))
    except ValueError:
        return web.json_response(
            {'error': 'Invalid limit/offset: must be integers'}, status=400
        )
    if limit < 1 or offset < 0:
        return web.json_response(
            {'error': 'Invalid limit/offset: limit must be >= 1, offset >= 0'},
            status=400,
        )
    limit = min(limit, _MAX_HISTORY_LIMIT)
    param_user = request.query.get('user') or None

    async with async_session_maker() as session:
        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner

        sessions = await WorkoutSessionRepository(session).get_history_page(
            owner.id, limit=limit, offset=offset
        )

    return web.json_response({
        'success': True,
        'data': [_serialize_session_summary(s) for s in sessions],
    })


@webapp_auth
async def api_get_history_session(request: web.Request) -> web.Response:
    """API endpoint (GYM-10): one workout session's detail — exercises →
    sets — for the "Історія" detail view (GYM-11).

    Path param: `session_id`. Query params: `user` (optional username,
    same trainer-viewing-a-client convention as `/api/statistics/volume`,
    used to authorize access to the session).
    Expects Authorization header with Telegram initData.
    """
    session_id_raw = request.match_info.get('session_id', '')
    if not session_id_raw.isdigit():
        return web.json_response({'error': 'Invalid session_id'}, status=400)
    session_id = int(session_id_raw)
    param_user = request.query.get('user') or None

    async with async_session_maker() as session:
        owner = await _resolve_program_owner(session, request, param_user)
        if isinstance(owner, web.Response):
            return owner

        workout_session = await WorkoutSessionRepository(
            session
        ).get_by_id_with_sets(session_id)
        if (
            workout_session is None
            or workout_session.user_id != owner.id
            or workout_session.completed_at is None
        ):
            return web.json_response({'error': 'Session not found'}, status=404)

        # Group by exercise, preserving first-seen order; sets sorted by
        # set_number within each exercise.
        order: list[str] = []
        by_exercise: dict[str, list] = {}
        for workout_set in workout_session.sets:
            if workout_set.exercise_name not in by_exercise:
                order.append(workout_set.exercise_name)
                by_exercise[workout_set.exercise_name] = []
            by_exercise[workout_set.exercise_name].append(workout_set)

        exercises = []
        for exercise_name in order:
            exercise_sets = sorted(
                by_exercise[exercise_name], key=lambda s: s.set_number
            )
            exercises.append({
                'exercise': exercise_name,
                'muscle_group': exercise_sets[0].muscle_group,
                'sets': [
                    {'set': s.set_number, 'weight': s.weight, 'reps': s.reps}
                    for s in exercise_sets
                ],
            })

        data = _serialize_session_summary(workout_session)
        data['exercises'] = exercises

    return web.json_response({'success': True, 'data': data})


def create_webapp() -> web.Application:
    """Create and configure the web application."""
    app = web.Application()

    # Mini App pages
    app.router.add_get('/nutrition', nutrition_handler)
    app.router.add_get('/profile', profile_handler)
    app.router.add_get('/meal-entry', meal_entry_handler)
    app.router.add_get('/workout', workout_handler)
    app.router.add_get('/statistics', statistics_handler)

    # API endpoints
    app.router.add_get('/api/user/settings', api_get_user_settings)
    app.router.add_post('/api/user/settings', api_update_user_settings)
    app.router.add_get('/api/user/sync-settings', api_get_sync_settings)
    app.router.add_post('/api/user/sync-settings', api_update_sync_settings)
    app.router.add_get('/api/nutrition/daily', api_get_daily_nutrition)
    app.router.add_post('/api/nutrition/daily', api_save_daily_nutrition)
    app.router.add_post('/api/nutrition/meal', api_add_meal)
    app.router.add_post('/api/nutrition/meal/photo', api_recognize_meal_photo)
    app.router.add_get('/api/nutrition/meals', api_get_today_meals)
    app.router.add_delete('/api/nutrition/meal/{id}', api_delete_meal)
    app.router.add_get('/api/nutrition/statistics', api_get_nutrition_statistics)
    app.router.add_get('/api/workout/program', api_get_workout_program)
    app.router.add_post('/api/workout/program/exercise', api_add_program_exercise)
    app.router.add_get('/api/exercises', api_search_exercises)
    app.router.add_get('/api/exercises/{id}', api_get_exercise)
    app.router.add_get('/api/workout/last-log', api_get_last_workout_log)
    app.router.add_post('/api/workout/session/start', api_start_workout_session)
    app.router.add_post(
        '/api/workout/session/exercise', api_sync_workout_session_exercise
    )
    app.router.add_post('/api/workout/log', api_save_workout_log)
    app.router.add_post('/api/workout/rest-timer', api_start_rest_timer)
    app.router.add_delete('/api/workout/rest-timer', api_cancel_rest_timer)
    app.router.add_delete('/api/workout/day', api_delete_workout_day)
    app.router.add_delete('/api/workout/exercise', api_delete_exercise)
    app.router.add_get('/api/statistics/volume', api_get_volume_statistics)
    app.router.add_get('/api/statistics/summary', api_get_statistics_summary)
    app.router.add_get('/api/statistics/exercises', api_get_exercises)
    app.router.add_get('/api/statistics/exercise-progress', api_get_exercise_progress)
    app.router.add_get('/api/statistics/records', api_get_records)
    app.router.add_get('/api/statistics/streak', api_get_streak)
    app.router.add_get('/api/statistics/achievements', api_get_achievements)
    app.router.add_get('/api/statistics/today', api_get_today_workout)
    app.router.add_get('/api/statistics/history', api_get_history)
    app.router.add_get(
        '/api/statistics/history/{session_id}', api_get_history_session
    )

    # Static files
    app.router.add_static('/static', TEMPLATES_DIR, name='static')

    return app


async def start_webapp(
    host: str = '0.0.0.0', port: int = 8080
) -> web.AppRunner | None:
    """
    Start the web application server.

    Returns None if the server fails to start (e.g., port already in use).
    """
    app = create_webapp()
    runner = web.AppRunner(app)
    await runner.setup()

    try:
        site = web.TCPSite(runner, host, port)
        await site.start()
        logger.info(f'Web server started at http://{host}:{port}')
        return runner
    except OSError as e:
        await runner.cleanup()
        logger.error(f'Failed to start web server on port {port}: {e}')
        return None


async def stop_webapp(runner: web.AppRunner) -> None:
    """Stop the web application server."""
    await runner.cleanup()
    logger.info('Web server stopped')
