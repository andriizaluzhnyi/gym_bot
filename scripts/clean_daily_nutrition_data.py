"""
Script to clean up daily_nutrition records that were incorrectly created
by the api_update_user_settings endpoint.
These records have values equal to user goals instead of actual consumption.
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import delete
from src.database.session import async_session_maker
from src.database.models import DailyNutrition


async def clean_data():
    """Delete all existing daily_nutrition records."""
    async with async_session_maker() as session:
        # Delete all records
        await session.execute(delete(DailyNutrition))
        await session.commit()
        print("✅ Очищено всі записи з daily_nutrition")


if __name__ == "__main__":
    print("🗑️  Очищення таблиці daily_nutrition...")
    asyncio.run(clean_data())
    print("✅ Готово!")
