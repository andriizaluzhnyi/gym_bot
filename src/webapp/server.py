"""Web server for Telegram Mini App."""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.database.repository import (
    DailyNutritionRepository,
    UserRepository,
    WorkoutSessionRepository,
    WorkoutSetRepository,
)
from src.database.session import async_session_maker
from src.services.google_calendar import GoogleCalendarService
from src.services.google_sheets import GoogleSheetsService
from src.services.personal_records import calculate_prs
from src.utils.datetime_utils import period_bounds_utc, to_local_date
from src.webapp.auth import TELEGRAM_USER_KEY, validate_telegram_webapp_data, webapp_auth

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / 'templates'
settings = get_settings()

# Global bot instance (will be set by run_bot)
_bot_instance = None


def set_bot_instance(bot):
    """Set the global bot instance."""
    global _bot_instance
    _bot_instance = bot


def get_bot_instance():
    """Get the global bot instance."""
    return _bot_instance


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


async def api_get_user_settings(request: web.Request) -> web.Response:
    """API endpoint to get user nutrition settings.

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
        nutrition = await user_repo.get_nutrition_settings(telegram_id)

        if not nutrition:
            return web.json_response({'error': 'User not found'}, status=404)

        return web.json_response({
            'success': True,
            'data': nutrition
        })


async def api_update_user_settings(request: web.Request) -> web.Response:
    """API endpoint to update user nutrition settings.

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

        # Get user first to get user_id
        user = await user_repo.get_by_telegram_id(telegram_id)
        if not user:
            return web.json_response({'error': 'User not found'}, status=404)

        # Update user nutrition goals
        user = await user_repo.update_nutrition_settings(
            telegram_id=telegram_id,
            age=body.get('age'),
            height=body.get('height'),
            weight=body.get('weight'),
            gender=body.get('gender'),
            daily_water_ml=body.get('daily_water_ml'),
            daily_calories=body.get('daily_calories'),
            daily_protein=body.get('daily_protein'),
            daily_fats=body.get('daily_fats'),
            daily_carbs=body.get('daily_carbs'),
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

        # Save daily nutrition record (increment only)
        from src.utils.datetime_utils import utcnow
        record = await daily_nutrition_repo.create(
            user_id=user.id,
            date=utcnow(),
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

        # Get today's total (sum of all records)
        from src.utils.datetime_utils import utcnow
        totals = await daily_nutrition_repo.get_today_total(
            user.id, utcnow()
        )

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

        # Create meal record
        from src.utils.datetime_utils import utcnow
        record = await daily_nutrition_repo.create(
            user_id=user.id,
            date=utcnow(),
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
                'meal_name': body.get('meal_name'),
                'calories': record.calories,
                'protein': record.protein,
                'fats': record.fats,
                'carbs': record.carbs,
                'created_at': record.created_at.isoformat(),
            }
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

        # Get user
        user = await user_repo.get_by_telegram_id(telegram_id)
        if not user:
            return web.json_response({'error': 'User not found'}, status=404)

        # Get today's meals (all records for today where water_ml is 0)
        from sqlalchemy import and_, select
        from src.database.models import DailyNutrition
        from src.utils.datetime_utils import utcnow

        start_of_day = utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_of_day = utcnow().replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

        result = await session.execute(
            select(DailyNutrition)
            .where(
                and_(
                    DailyNutrition.user_id == user.id,
                    DailyNutrition.date >= start_of_day,
                    DailyNutrition.date <= end_of_day,
                    DailyNutrition.water_ml == 0,  # Only meal records
                )
            )
            .order_by(DailyNutrition.created_at.desc())
        )
        meals = result.scalars().all()

        return web.json_response({
            'success': True,
            'data': [
                {
                    'id': meal.id,
                    'calories': meal.calories,
                    'protein': meal.protein,
                    'fats': meal.fats,
                    'carbs': meal.carbs,
                    'created_at': meal.created_at.isoformat(),
                }
                for meal in meals
            ]
        })


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


async def _resolve_statistics_owner(
    session: AsyncSession, request: web.Request, param_user: str | None
):
    """Resolve whose statistics a `/api/statistics/*` request is for.

    Defaults to the caller's own `telegram_id` (from `initData`, via
    `@webapp_auth`); an explicit `user` query param lets a trainer view a
    client's stats instead — same convention as `/workout?user=<name>`.
    """
    user_repo = UserRepository(session)
    if param_user:
        return await user_repo.get_by_username(param_user)
    telegram_id = request[TELEGRAM_USER_KEY].get('id')
    return await user_repo.get_by_telegram_id(telegram_id) if telegram_id else None


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
        owner = await _resolve_statistics_owner(session, request, param_user)
        if not owner:
            return web.json_response({'error': 'User not found'}, status=404)

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
        owner = await _resolve_statistics_owner(session, request, param_user)
        if not owner:
            return web.json_response({'error': 'User not found'}, status=404)

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
        owner = await _resolve_statistics_owner(session, request, param_user)
        if not owner:
            return web.json_response({'error': 'User not found'}, status=404)

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
        owner = await _resolve_statistics_owner(session, request, param_user)
        if not owner:
            return web.json_response({'error': 'User not found'}, status=404)

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
        owner = await _resolve_statistics_owner(session, request, param_user)
        if not owner:
            return web.json_response({'error': 'User not found'}, status=404)

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


async def api_get_workout_program(request: web.Request) -> web.Response:
    """API endpoint to get workout program exercises for a session.

    Query params: user, day (optional), muscle (optional).
    Expects Authorization header with Telegram initData.
    """
    init_data = request.headers.get('Authorization', '')
    user_data = validate_telegram_webapp_data(init_data)

    if not user_data:
        return web.json_response({'error': 'Unauthorized'}, status=401)

    user_name = request.query.get('user', '')
    day = request.query.get('day', '')
    muscle = request.query.get('muscle', '')

    if not user_name:
        return web.json_response(
            {'error': 'Missing required param: user'}, status=400
        )

    try:
        sheets_service = GoogleSheetsService()
        programs = await sheets_service.get_workout_programs(
            limit=100, user_name=user_name
        )

        # Filter by day if provided
        if day:
            programs = [
                p for p in programs if str(p.get('day', '')) == str(day)
            ]

        # Filter by muscle group if provided
        if muscle:
            programs = [
                p for p in programs if p.get('muscle_group') == muscle
            ]

        return web.json_response({
            'success': True,
            'data': {
                'exercises': programs,
            },
        })

    except Exception as e:
        logger.error(f'Error loading workout program: {e}')
        return web.json_response(
            {'error': 'Failed to load program'}, status=500
        )


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

    from src.utils.datetime_utils import utcnow

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

    return web.json_response({
        'success': True,
        'synced_to_sheets': synced_to_sheets,
    })


async def api_start_rest_timer(request: web.Request) -> web.Response:
    """API endpoint to start rest timer and send notification after 60 seconds.

    Expects Authorization header with Telegram initData.
    Body: { duration_seconds: 60 }
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

    if not telegram_user_id:
        return web.json_response(
            {'error': 'Missing telegram user id'}, status=400
        )

    # Log received parameters for debugging
    logger.info(
        f"Rest timer request: user={workout_user}, "
        f"day={workout_day}, muscle={workout_muscle}"
    )

    # Schedule notification using bot
    try:
        import asyncio
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

        # Start task in background
        asyncio.create_task(send_delayed_notification())

        return web.json_response({
            'success': True,
            'message': f'Notification scheduled in {duration_seconds}s'
        })

    except Exception as e:
        logger.error(f'Error scheduling rest timer notification: {e}')
        return web.json_response(
            {'error': 'Failed to schedule notification'}, status=500
        )


async def api_delete_workout_day(request: web.Request) -> web.Response:
    """API endpoint to delete entire workout day.

    Query params: user, day.
    Expects Authorization header with Telegram initData.
    """
    init_data = request.headers.get('Authorization', '')
    user_data = validate_telegram_webapp_data(init_data)

    if not user_data:
        return web.json_response({'error': 'Unauthorized'}, status=401)

    user_name = request.query.get('user', '')
    day = request.query.get('day', '')

    if not user_name or not day:
        return web.json_response(
            {'error': 'Missing required params: user, day'}, status=400
        )

    try:
        sheets_service = GoogleSheetsService()
        success = await sheets_service.delete_workout_day(user_name, day)

        if success:
            return web.json_response({'success': True})
        else:
            return web.json_response(
                {'error': 'Failed to delete day'}, status=500
            )

    except Exception as e:
        logger.error(f'Error deleting workout day: {e}')
        return web.json_response(
            {'error': 'Failed to delete day'}, status=500
        )


async def api_delete_exercise(request: web.Request) -> web.Response:
    """API endpoint to delete specific exercise from workout program.

    Query params: user, day, exercise.
    Expects Authorization header with Telegram initData.
    """
    init_data = request.headers.get('Authorization', '')
    user_data = validate_telegram_webapp_data(init_data)

    if not user_data:
        return web.json_response({'error': 'Unauthorized'}, status=401)

    user_name = request.query.get('user', '')
    day = request.query.get('day', '')
    exercise = request.query.get('exercise', '')

    if not user_name or not day or not exercise:
        return web.json_response(
            {'error': 'Missing required params: user, day, exercise'},
            status=400
        )

    try:
        sheets_service = GoogleSheetsService()
        success = await sheets_service.delete_exercise(
            user_name, day, exercise
        )

        if success:
            return web.json_response({'success': True})
        else:
            return web.json_response(
                {'error': 'Exercise not found'}, status=404
            )

    except Exception as e:
        logger.error(f'Error deleting exercise: {e}')
        return web.json_response(
            {'error': 'Failed to delete exercise'}, status=500
        )


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
        owner = await _resolve_statistics_owner(session, request, param_user)
        if not owner:
            return web.json_response({'error': 'User not found'}, status=404)

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
        owner = await _resolve_statistics_owner(session, request, param_user)
        if not owner:
            return web.json_response({'error': 'User not found'}, status=404)

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
    app.router.add_get('/api/nutrition/meals', api_get_today_meals)
    app.router.add_get('/api/workout/program', api_get_workout_program)
    app.router.add_get('/api/workout/last-log', api_get_last_workout_log)
    app.router.add_post('/api/workout/session/start', api_start_workout_session)
    app.router.add_post(
        '/api/workout/session/exercise', api_sync_workout_session_exercise
    )
    app.router.add_post('/api/workout/log', api_save_workout_log)
    app.router.add_post('/api/workout/rest-timer', api_start_rest_timer)
    app.router.add_delete('/api/workout/day', api_delete_workout_day)
    app.router.add_delete('/api/workout/exercise', api_delete_exercise)
    app.router.add_get('/api/statistics/volume', api_get_volume_statistics)
    app.router.add_get('/api/statistics/summary', api_get_statistics_summary)
    app.router.add_get('/api/statistics/exercises', api_get_exercises)
    app.router.add_get('/api/statistics/exercise-progress', api_get_exercise_progress)
    app.router.add_get('/api/statistics/records', api_get_records)
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
