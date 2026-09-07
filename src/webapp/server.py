"""Web server for Telegram Mini App."""

import json
import logging
from pathlib import Path

from aiohttp import web

from src.config import get_settings
from src.database.repository import (
    DailyNutritionRepository,
    UserRepository,
    WorkoutSessionRepository,
)
from src.database.session import async_session_maker
from src.services.google_calendar import GoogleCalendarService
from src.services.google_sheets import GoogleSheetsService
from src.webapp.auth import validate_telegram_webapp_data, webapp_auth

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
    telegram_id = request['telegram_user'].get('id')
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
    telegram_id = request['telegram_user'].get('id')
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


async def api_save_workout_log(request: web.Request) -> web.Response:
    """API endpoint to save a completed workout log.

    Expects Authorization header with Telegram initData.
    Body: { user, day, exercises: [{ exercise, muscle_group,
            planned_sets_reps, sets: [{ set, weight, reps }] }] }

    The database is the source of truth (GYM-2): the session and its sets
    are saved there first, and that write must succeed for the request to
    succeed. Google Sheets is written to afterwards, and only if the
    workout's owner opted in via ``/api/user/sync-settings``; a Sheets
    failure is logged but never fails the request (the DB copy already
    exists).
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

    from datetime import datetime

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
    for ex in exercises:
        for s in ex.get('sets', []):
            weight = s.get('weight', '')
            reps = s.get('reps', '')

            log_entries.append({
                'date': date_str,
                'exercise': ex.get('exercise', ''),
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

            db_sets.append({
                'exercise_name': ex.get('exercise', ''),
                'muscle_group': ex.get('muscle_group') or None,
                'set_number': s.get('set'),
                'weight': float(weight),
                'reps': int(reps),
                'planned_sets_reps': ex.get('planned_sets_reps') or None,
            })

    async with async_session_maker() as session:
        owner = await UserRepository(session).get_by_username(user_name)
        if not owner:
            return web.json_response({'error': 'User not found'}, status=404)

        try:
            await WorkoutSessionRepository(session).create_session_with_sets(
                user_id=owner.id,
                performed_at=performed_at,
                day=day_int,
                muscle_group=muscle or None,
                duration_seconds=duration_seconds,
                sets=db_sets,
            )
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f'Error saving workout to DB: {e}')
            return web.json_response(
                {'error': 'Failed to save workout'}, status=500
            )

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


def create_webapp() -> web.Application:
    """Create and configure the web application."""
    app = web.Application()

    # Mini App pages
    app.router.add_get('/nutrition', nutrition_handler)
    app.router.add_get('/profile', profile_handler)
    app.router.add_get('/meal-entry', meal_entry_handler)
    app.router.add_get('/workout', workout_handler)

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
    app.router.add_post('/api/workout/log', api_save_workout_log)
    app.router.add_post('/api/workout/rest-timer', api_start_rest_timer)
    app.router.add_delete('/api/workout/day', api_delete_workout_day)
    app.router.add_delete('/api/workout/exercise', api_delete_exercise)

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
