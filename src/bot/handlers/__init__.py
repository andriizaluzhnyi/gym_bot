"""Bot handlers package."""

from aiogram import Router

from src.bot.handlers.admin import router as admin_router
from src.bot.handlers.booking import router as booking_router
from src.bot.handlers.schedule import router as schedule_router
from src.bot.handlers.start import router as start_router
from src.bot.handlers.workout_program import router as workout_program_router


def setup_routers() -> Router:
    """Setup and return main router with all handlers."""
    main_router = Router()

    main_router.include_router(start_router)
    main_router.include_router(schedule_router)
    main_router.include_router(booking_router)
    main_router.include_router(admin_router)
    main_router.include_router(workout_program_router)

    return main_router
