"""Test adding multiple water entries."""

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path

from src.database.models import Base
from src.database.repository import DailyNutritionRepository, UserRepository
from src.database.session import async_session_maker, engine


async def test_multiple_entries():
    """Test creating multiple nutrition entries for the same day."""
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_maker() as session:
        user_repo = UserRepository(session)
        nutrition_repo = DailyNutritionRepository(session)

        # Create test user
        user, created = await user_repo.get_or_create(
            telegram_id=123456789,
            first_name="Test",
            last_name="User"
        )

        if created:
            print(f"✓ Created test user: {user.full_name}")
        else:
            print(f"✓ Found existing user: {user.full_name}")

        # Add multiple water entries
        print("\nAdding water entries:")
        entry1 = await nutrition_repo.create(
            user_id=user.id,
            date=datetime.utcnow(),
            water_ml=100,
            calories=0,
            protein=0,
            fats=0,
            carbs=0,
        )
        print(f"  +100ml (id={entry1.id})")

        entry2 = await nutrition_repo.create(
            user_id=user.id,
            date=datetime.utcnow(),
            water_ml=200,
            calories=0,
            protein=0,
            fats=0,
            carbs=0,
        )
        print(f"  +200ml (id={entry2.id})")

        entry3 = await nutrition_repo.create(
            user_id=user.id,
            date=datetime.utcnow(),
            water_ml=250,
            calories=0,
            protein=0,
            fats=0,
            carbs=0,
        )
        print(f"  +250ml (id={entry3.id})")

        await session.commit()

        # Get today's total
        totals = await nutrition_repo.get_today_total(
            user.id, datetime.utcnow()
        )

        print(f"\n✓ Today's total water: {totals['water_ml']}ml")
        print(f"  Expected: 550ml")

        if totals['water_ml'] == 550:
            print("\n✅ TEST PASSED!")
        else:
            print("\n❌ TEST FAILED!")

    # Check database directly
    db_path = Path("data/gym_bot.db")
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM daily_nutrition
            WHERE user_id = ?
        """, (user.id,))
        count = cursor.fetchone()[0]
        print(f"\n✓ Total records in DB: {count}")
        conn.close()


if __name__ == "__main__":
    asyncio.run(test_multiple_entries())
