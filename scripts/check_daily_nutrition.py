"""Check daily_nutrition table structure."""

import sqlite3
from pathlib import Path

db_path = Path("data/gym_bot.db")

if db_path.exists():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    print("Таблиці в базі даних:")
    for table in tables:
        print(f"  - {table}")

    # Check daily_nutrition structure
    if 'daily_nutrition' in tables:
        print("\nСтруктура таблиці daily_nutrition:")
        cursor.execute("PRAGMA table_info(daily_nutrition)")
        for row in cursor.fetchall():
            print(f"  {row[1]:15} {row[2]:15} {'NOT NULL' if row[3] else 'NULL':10} {f'DEFAULT {row[4]}' if row[4] else ''}")

        # Check indexes
        print("\nІндекси таблиці daily_nutrition:")
        cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='daily_nutrition'")
        for row in cursor.fetchall():
            print(f"  - {row[0]}")

        # Check data count
        cursor.execute("SELECT COUNT(*) FROM daily_nutrition")
        count = cursor.fetchone()[0]
        print(f"\nКількість записів: {count}")

        if count > 0:
            print("\nОстанні 5 записів:")
            cursor.execute("""
                SELECT id, user_id, date, water_ml, calories, protein, fats, carbs
                FROM daily_nutrition
                ORDER BY date DESC
                LIMIT 5
            """)
            for row in cursor.fetchall():
                print(f"  ID={row[0]}, user_id={row[1]}, date={row[2]}, water={row[3]}мл, cal={row[4]}, P={row[5]}г, F={row[6]}г, C={row[7]}г")
    else:
        print("\n⚠️ Таблиця daily_nutrition НЕ знайдена!")

    conn.close()
else:
    print(f"База даних не знайдена: {db_path}")
