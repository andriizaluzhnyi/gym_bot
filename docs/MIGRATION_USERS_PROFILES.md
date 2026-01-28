# Міграція: Розділення таблиці users на users та profiles

## Що було зроблено

Таблиця `users` була розділена на дві окремі таблиці:
- **users** - базова інформація про користувача (telegram_id, ім'я, телефон, права адміністратора)
- **profiles** - додаткова інформація про профіль (вік, зріст, вага, стать, норми БЖУ)

## Зміни в структурі

### Таблиця `users` (оновлена)
Залишилися поля:
- id
- telegram_id
- username
- first_name
- last_name
- phone
- is_admin
- is_active
- notifications_enabled
- created_at
- updated_at

Видалені поля (переміщені в profiles):
- age
- height
- weight
- gender
- daily_water_ml
- daily_calories
- daily_protein
- daily_fats
- daily_carbs

### Таблиця `profiles` (нова)
Поля:
- id (primary key)
- user_id (foreign key до users.id, unique)
- age
- height
- weight
- gender
- daily_water_ml
- daily_calories
- daily_protein
- daily_fats
- daily_carbs
- created_at
- updated_at

## Зміни в коді

### Моделі (src/database/models.py)
- Додано нову модель `Profile`
- У моделі `User` видалено поля профілю та додано relationship до `Profile`

### Repository (src/database/repository.py)
- Додано новий клас `ProfileRepository` з методами:
  - `get_by_user_id()` - отримати профіль користувача
  - `get_or_create()` - отримати або створити профіль
  - `update()` - оновити налаштування профілю
  - `get_settings()` - отримати налаштування як словник

- У `UserRepository` методи `update_nutrition_settings()` та `get_nutrition_settings()`
  тепер працюють через `ProfileRepository` (deprecated, але залишені для сумісності)

### Хендлери
Хендлери profile.py та nutrition.py продовжують працювати через існуючі методи UserRepository,
які тепер внутрішньо використовують ProfileRepository.

## Як запустити міграцію

```bash
# Активувати віртуальне оточення
source venv/bin/activate  # Linux/Mac
# або
.\venv\Scripts\Activate.ps1  # Windows PowerShell

# Запустити міграційний скрипт
python scripts/migrate_split_users_table.py
```

## Що робить міграційний скрипт

1. Створює нову таблицю `profiles`
2. Перевіряє наявність старих полів у таблиці `users`
3. Копіює дані з `users` в `profiles` (тільки для користувачів з заповненими даними)
4. Видаляє старі поля з таблиці `users`
5. Виконує перевірку успішності міграції

## Зворотна сумісність

Весь існуючий код продовжує працювати без змін завдяки:
- Deprecated методам у `UserRepository`, які внутрішньо викликають `ProfileRepository`
- Збереженню API для хендлерів та webapp

## Переваги нової структури

1. **Краща нормалізація** - розділення базової інформації користувача та профілю
2. **Гнучкість** - профіль може бути необов'язковим
3. **Продуктивність** - менше даних завантажується при отриманні базової інформації користувача
4. **Розширюваність** - легше додавати нові поля до профілю без перевантаження таблиці users
