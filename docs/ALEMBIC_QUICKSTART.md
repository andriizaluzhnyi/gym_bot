# Швидкий старт з Alembic

## Налаштування (вже виконано)

✅ Alembic встановлено та ініціалізовано
✅ Створено початкову міграцію з UUID
✅ База даних позначена поточною версією

## Щоденне використання

### Створити нову міграцію після зміни моделей

```bash
# Windows PowerShell
c:/Users/ZALUZHNYI/projects/gymbro/venv/Scripts/alembic.exe revision --autogenerate -m "опис_змін"

# Або через helper скрипт
python scripts/migrate.py create "опис_змін" --auto
```

### Застосувати міграції

```bash
# Застосувати всі нові міграції
alembic upgrade head

# Або через helper
python scripts/migrate.py upgrade
```

### Відкотити останню міграцію

```bash
alembic downgrade -1

# Або через helper
python scripts/migrate.py downgrade
```

### Перевірити поточний стан

```bash
# Поточна версія бази
alembic current

# Історія міграцій
alembic history

# Перевірити чи потрібні міграції
alembic check
```

## Приклад робочого процесу

### 1. Додати нове поле в модель

Файл: `src/database/models.py`

```python
class User(Base):
    __tablename__ = "users"

    # ... існуючі поля

    # Нове поле
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
```

### 2. Створити міграцію

```bash
alembic revision --autogenerate -m "add_bio_to_user"
```

### 3. Перевірити згенеровану міграцію

Відкрийте файл у `alembic/versions/` та переконайтеся що все правильно.

### 4. Застосувати міграцію

```bash
alembic upgrade head
```

### 5. Перевірити результат

```bash
alembic current
# Має показати нову версію
```

## Важливо! ⚠️

### Перед production deploy

1. Зробіть backup бази даних
2. Протестуйте міграцію на staging
3. Перевірте що можна відкотити (`downgrade`)

### Перед commit

1. Перевірте згенеровану міграцію
2. Переконайтеся що `upgrade()` та `downgrade()` працюють
3. Додайте коментарі якщо потрібно

## Поточний стан

```
База даних: gym_bot.db (SQLite)
Версія: c833063f0b93 (initial_setup_with_uuid)
Останнє оновлення: 2026-01-28
```

## Корисні команди

```bash
# Подивитись SQL що буде виконано (без виконання)
alembic upgrade head --sql

# Відкотити всі міграції
alembic downgrade base

# Застосувати конкретну версію
alembic upgrade <revision_id>

# Об'єднати гілки міграцій
alembic merge heads -m "merge description"
```

## Troubleshooting

### "Target database is not up to date"
```bash
alembic upgrade head
```

### "Multiple heads"
```bash
alembic merge heads -m "merge"
```

### База і моделі не співпадають
```bash
alembic revision --autogenerate -m "sync_models"
alembic upgrade head
```

## Документація

Детальна документація: [alembic/README.md](alembic/README.md)
