# Alembic Міграції

Цей проект використовує Alembic для управління міграціями бази даних.

## Структура

```
alembic/
  ├── versions/          # Папка з файлами міграцій
  ├── env.py            # Конфігурація середовища Alembic
  └── script.py.mako    # Шаблон для нових міграцій
alembic.ini             # Головний конфігураційний файл
```

## Основні команди

### Перегляд поточного стану

```bash
# Подивитись поточну версію бази даних
alembic current

# Подивитись історію міграцій
alembic history

# Подивитись детальну інформацію про міграцію
alembic show <revision_id>
```

### Створення нових міграцій

```bash
# Автоматично створити міграцію на основі змін в моделях
alembic revision --autogenerate -m "опис змін"

# Створити порожню міграцію (для ручних змін)
alembic revision -m "опис змін"
```

### Застосування міграцій

```bash
# Застосувати всі міграції до найновішої версії
alembic upgrade head

# Застосувати міграції до конкретної версії
alembic upgrade <revision_id>

# Застосувати N міграцій вперед
alembic upgrade +2

# Відкотити одну міграцію назад
alembic downgrade -1

# Відкотити до конкретної версії
alembic downgrade <revision_id>

# Відкотити всі міграції
alembic downgrade base
```

### Інші корисні команди

```bash
# Перевірити, чи є невиконані міграції
alembic check

# Створити міграцію з нової гілки
alembic revision -m "опис" --head=<revision_id>

# Об'єднати гілки міграцій
alembic merge heads -m "merge description"
```

## Робочий процес

### 1. Внесення змін в моделі

Відредагуйте файл `src/database/models.py`:

```python
class User(Base):
    __tablename__ = "users"

    # Додайте нове поле
    new_field: Mapped[str | None] = mapped_column(String(100), nullable=True)
```

### 2. Створення міграції

```bash
alembic revision --autogenerate -m "add_new_field_to_user"
```

Alembic створить файл міграції в `alembic/versions/` з автоматично згенерованими функціями `upgrade()` та `downgrade()`.

### 3. Перевірка міграції

Відкрийте створений файл та переконайтеся, що зміни правильні. Іноді потрібно вручну відкоригувати міграцію.

### 4. Застосування міграції

```bash
# Для production
alembic upgrade head

# Для тестування можна спочатку застосувати і відкотити
alembic upgrade head
alembic downgrade -1
```

## Поточні міграції

### 20260128_0403-c833063f0b93_initial_setup_with_uuid
**Створено**: 2026-01-28

Початкова міграція з UUID для користувачів:
- Users: UUID primary key
- Profiles: UUID для id та user_id
- Bookings: UUID для user_id
- DailyNutrition: UUID для user_id
- Додано індекси для оптимізації
- Видалено застарілі таблиці (user_id_mapping, workout_programs)

## Особливості конфігурації

### SQLite Batch Mode

Для SQLite використовується `render_as_batch=True`, що дозволяє виконувати ALTER TABLE операції, які SQLite не підтримує напряму.

### Async Engine

Alembic налаштований для роботи з async SQLAlchemy engine через `async_engine_from_config`.

### Автоматичне завантаження моделей

`env.py` налаштований так, щоб автоматично імпортувати всі моделі з `src.database.models` для autogenerate.

## Troubleshooting

### Помилка "can't adapt type 'UUID'"

Переконайтеся, що використовується клас `GUID` з `models.py`, який автоматично конвертує UUID в правильний тип для SQLite/PostgreSQL.

### Помилка "Target database is not up to date"

```bash
# Подивіться поточний стан
alembic current

# Застосуйте всі міграції
alembic upgrade head
```

### Конфлікт міграцій (multiple heads)

```bash
# Подивіться heads
alembic heads

# Об'єднайте гілки
alembic merge heads -m "merge conflicting migrations"
```

### База даних не в sync з моделями

```bash
# Створіть нову міграцію для синхронізації
alembic revision --autogenerate -m "sync_with_models"

# Перевірте згенеровану міграцію
# Застосуйте її
alembic upgrade head
```

## Best Practices

1. **Завжди перевіряйте згенеровані міграції** - autogenerate може не виявити всі зміни
2. **Тестуйте downgrade** - переконайтеся, що можна відкотити зміни
3. **Використовуйте описові назви** - легко зрозуміти що робить міграція
4. **Один логічний зміна = одна міграція** - не змішуйте різні зміни
5. **Backups** - завжди робіть backup перед застосуванням міграцій на production
6. **Перевіряйте на staging** - спочатку тестуйте на staging середовищі

## Deployment

### Development

```bash
alembic upgrade head
```

### Production

```bash
# Створіть backup бази даних
# Перевірте, які міграції будуть застосовані
alembic upgrade head --sql > migration.sql

# Застосуйте міграції
alembic upgrade head
```

### Heroku

Додайте до `Procfile`:

```
release: alembic upgrade head
```

Або виконайте вручну:

```bash
heroku run alembic upgrade head -a your-app-name
```

## Додаткові ресурси

- [Alembic Documentation](https://alembic.sqlalchemy.org/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Alembic Tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
