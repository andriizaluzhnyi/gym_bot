# Gym Bot 🏋️

Telegram бот для управління записами на тренування з синхронізацією Google Calendar та Google Sheets.

## Функціонал

- 📅 **Розклад тренувань** — перегляд доступних тренувань
- 📝 **Запис на тренування** — онлайн запис з перевіркою вільних місць
- 🔔 **Нагадування** — автоматичні нагадування за 24 години та 2 години
- 📊 **Google Calendar** — синхронізація тренувань з календарем
- 📋 **Google Sheets** — опційне дзеркало логів тренувань (БД — основне сховище)
- 🍎 **Харчування (Mini App)** — трекінг калорій, білків, жирів, вуглеводів та води
- 🏋️ **Тренування (Mini App)** — лог підходів (вага/повтори) за програмою дня чи
  групи м'язів, з чернетками, що автозберігаються в БД під час тренування
- 📈 **Статистика тренувань (Mini App)** — об'єм (тоннаж) за тиждень/місяць/увесь
  час у розрізі груп м'язів і загальна активність (кількість тренувань,
  середня тривалість, улюблена група)
- 👨‍💼 **Адмін-панель** — управління тренуваннями для тренера
- 🔐 **UUID користувачів** — унікальні ідентифікатори для масштабованості

## Швидкий старт

### 1. Клонування репозиторію

```bash
git clone https://github.com/andriizaluzhnyi/gym_bot.git
cd gym_bot
```

### 2. Створення віртуального середовища

```bash
# Linux/Mac
python3 -m venv venv
source venv/bin/activate

# Windows PowerShell
python -m venv venv
.\venv\Scripts\Activate.ps1

# Windows CMD
python -m venv venv
venv\Scripts\activate.bat
```

### 3. Встановлення залежностей

```bash
pip install -e .
```

Встановлені пакети включають:

- `aiogram 3.3.0+` — Telegram Bot API
- `sqlalchemy 2.0.0+` — ORM з async підтримкою
- `alembic 1.13.0+` — Міграції бази даних
- `aiosqlite` — Async SQLite драйвер
- `asyncpg` — Async PostgreSQL драйвер (опціонально)
- `google-api-python-client` — Google API

### 4. Налаштування конфігурації

Створіть файл `.env` у корені проекту:

```env
# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token_here
ADMIN_USER_IDS=123456789,987654321

# Database (виберіть один варіант)
# SQLite (за замовчуванням)
DATABASE_URL=sqlite+aiosqlite:///./gym_bot.db

# PostgreSQL (production)
# DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/gym_bot

# Google API
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_CALENDAR_ID=your_calendar@group.calendar.google.com
GOOGLE_SPREADSHEET_ID=your_spreadsheet_id

# Webapp (опціонально)
WEBAPP_URL=https://your-domain.com
WEBAPP_PORT=8080
```

### 5. Налаштування бази даних

Проект підтримує як SQLite, так і PostgreSQL. Оберіть відповідний варіант:

#### Варіант А: SQLite (для розробки та тестування)

SQLite не потребує додаткового налаштування сервера. Просто встановіть URL у `.env`:

```env
DATABASE_URL=sqlite+aiosqlite:///./gym_bot.db
```

База даних буде створена автоматично при першому запуску.

#### Варіант Б: PostgreSQL (для production)

**5.1. Встановлення PostgreSQL**
Linux (Ubuntu/Debian):

```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

macOS (через Homebrew):

```bash
brew install postgresql
brew services start postgresql
```

Windows:

- Завантажте інсталятор з [postgresql.org](https://www.postgresql.org/download/windows/)
- Запустіть інсталятор та слідуйте інструкціям
**5.2. Створення бази даних та користувача**

```bash
# Увійдіть у PostgreSQL
sudo -u postgres psql

# Або на Windows
psql -U postgres
```

Виконайте SQL команди:

```sql
-- Створіть користувача
CREATE USER gym_bot_user WITH PASSWORD 'your_secure_password';

-- Створіть базу даних
CREATE DATABASE gym_bot OWNER gym_bot_user;

-- Надайте права
GRANT ALL PRIVILEGES ON DATABASE gym_bot TO gym_bot_user;

-- Вийдіть
\q
```

**5.3. Налаштуйте DATABASE_URL у `.env`:**

```env
DATABASE_URL=postgresql+asyncpg://gym_bot_user:your_secure_password@localhost:5432/gym_bot
```

### 6. Запуск міграцій бази даних

Проект використовує Alembic для управління схемою бази даних.

**6.1. Перевірте поточний стан бази:**

```bash
# Windows
.\venv\Scripts\alembic.exe current

# Linux/Mac
alembic current
```

Якщо база нова, ви побачите: `(empty)`

**6.2. Застосуйте всі міграції:**

```bash
# Windows
.\venv\Scripts\alembic.exe upgrade head

# Linux/Mac
alembic upgrade head

# Або через helper скрипт (працює на всіх ОС)
python scripts/migrate.py upgrade
```

Ви побачите:
```
INFO  [alembic.runtime.migration] Running upgrade  -> c833063f0b93, initial_setup_with_uuid
```

**6.3. Перевірте що міграція застосована:**

```bash
alembic current
```

Має показати: `c833063f0b93 (head)`

### 7. Налаштування Google API

#### 7.1. Створення проекту в Google Cloud Console

1. Перейдіть на [Google Cloud Console](https://console.cloud.google.com/)
2. Натисніть **Select a project** → **New Project**
3. Введіть назву проекту (наприклад, "Gym Bot")
4. Натисніть **Create**

#### 7.2. Увімкнення API

1. У лівому меню виберіть **APIs & Services** → **Library**
2. Знайдіть і увімкніть:
   - **Google Calendar API**
   - **Google Sheets API**

#### 7.3. Створення Service Account

1. Перейдіть у **APIs & Services** → **Credentials**
2. Натисніть **Create Credentials** → **Service Account**
3. Заповніть:
   - Service account name: `gym-bot-service`
   - Description: `Service account for Gym Bot`
4. Натисніть **Create and Continue**
5. Натисніть **Done**

#### 7.4. Створення ключа

1. Знайдіть створений Service Account у списку
2. Натисніть на нього → вкладка **Keys**
3. **Add Key** → **Create new key**
4. Оберіть формат **JSON**
5. Збережіть завантажений файл як `credentials.json` у корені проекту

#### 7.5. Налаштування Google Calendar

1. Відкрийте [Google Calendar](https://calendar.google.com/)
2. Створіть новий календар для бота:
   - Settings → **Add calendar** → **Create new calendar**
   - Name: `Gym Bot Trainings`
3. Перейдіть у налаштування створеного календаря
4. Скопіюйте **Calendar ID** (виглядає як `xxx@group.calendar.google.com`)
5. У розділі **Share with specific people** додайте email вашого Service Account з правами **Make changes to events**
   - Email Service Account можна знайти у файлі `credentials.json` (поле `client_email`)

#### 7.6. Налаштування Google Sheets

1. Відкрийте [Google Sheets](https://sheets.google.com/)
2. Створіть нову таблицю для бота
3. Натисніть **Share** → додайте email Service Account з правами **Editor**
4. Скопіюйте **Spreadsheet ID** з URL:
   - URL: `https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit`
5. Додайте ID у `.env`

### 8. Створення Telegram бота

1. Знайдіть [@BotFather](https://t.me/BotFather) у Telegram
2. Відправте команду `/newbot`
3. Введіть назву бота (наприклад, "My Gym Bot")
4. Введіть username бота (має закінчуватись на `bot`, наприклад `my_gym_bot`)
5. Скопіюйте отриманий токен у `.env` як `TELEGRAM_BOT_TOKEN`

Опціональні налаштування:
```
/setdescription - Опис бота
/setabouttext - Текст про бота
/setcommands - Налаштування команд
```

Команди для `/setcommands`:
```
start - Почати роботу з ботом
schedule - Розклад тренувань
my - Мої записи
profile - Мій профіль
nutrition - Харчування
help - Допомога
```

### 9. Запуск бота

```bash
python -m src.main
```

Або через helper скрипт:
```bash
python src/main.py
```

Бот має запуститись і вивести:
```
INFO - Bot started successfully
INFO - Notification scheduler started
```

### 10. Перевірка роботи

1. Знайдіть вашого бота у Telegram
2. Натисніть **Start** або відправте `/start`
3. Бот має відповісти привітанням та показати головне меню

## Docker (опціонально)

### Підготовка

1. Встановіть [Docker](https://docs.docker.com/get-docker/) та [Docker Compose](https://docs.docker.com/compose/install/)
2. Створіть `.env` файл як описано вище
3. Розмістіть `credentials.json` у корені проекту

### Запуск через Docker Compose

```bash
# Побудуйте контейнер
docker-compose build

# Запустіть бота
docker-compose up -d

# Перегляд логів
docker-compose logs -f bot

# Зупинити бота
docker-compose down
```

### Production deployment (Heroku/Railway/Render)

Додайте до `Procfile` (якщо потрібно):

```text
release: alembic upgrade head
web: python -m src.main
```

Це гарантує, що міграції застосуються перед кожним deploy.

## Команди бота

При запущеному `WEBAPP_URL` бот виставляє глобальну chat-menu-кнопку
`📱 Щоденник` (відкриває `/nutrition`) і реєструє список команд через
`set_my_commands` (`src/bot/bot.py: configure_bot_commands`) — обидва
виконуються один раз при старті, а не на кожен `/start`.

### Для користувачів

- `/start` — почати роботу з ботом
- `/help` — довідка
- `/nutrition` — харчування (Mini App)
- `/statistics` — статистика тренувань (Mini App)
- `/schedule` — розклад тренувань
- `/my` — мої записи
- Кнопки головного меню: `🍎 Харчування` / `🏋️ Тренування` / `📊 Статистика`
  (WebApp, лише при заданому `WEBAPP_URL`), `👤 Профіль`, `📅 Розклад`,
  `📝 Мої записи`, `ℹ️ Допомога`

### Для адмінів (тренер)

- `/admin` — адмін-панель
- Кнопки адмінського меню (зверху над звичайними): `💪 Програма тренувань`,
  `📋 Переглянути програми`, `➕ Додати тренування`, `📈 Адмін-статистика`

## Структура проекту

```plaintext
gym_bot/
├── alembic/                     # Міграції бази даних
│   ├── versions/                # Файли міграцій
│   ├── env.py                   # Alembic environment
│   └── README.md
├── scripts/                     # Допоміжні скрипти
│   ├── migrate.py                       # Helper для міграцій
│   ├── check_daily_nutrition.py         # Діагностика даних харчування
│   └── clean_daily_nutrition_data.py    # Очищення даних харчування
├── src/
│   ├── bot/
│   │   ├── handlers/
│   │   │   ├── start.py             # /start, /help
│   │   │   ├── schedule.py          # Розклад тренувань
│   │   │   ├── booking.py           # Запис/скасування
│   │   │   ├── nutrition.py         # /nutrition — трекінг харчування
│   │   │   ├── workout_program.py   # Програми тренувань (адмін)
│   │   │   ├── workout_statistics.py # /statistics — статистика тренувань
│   │   │   ├── user_profile.py      # Профіль користувача
│   │   │   └── admin.py             # Адмін функції
│   │   ├── keyboards.py         # Клавіатури
│   │   ├── calendar_picker.py   # Календар для вибору дати
│   │   └── bot.py               # Головний модуль бота
│   ├── services/
│   │   ├── google_calendar.py   # Інтеграція з Calendar
│   │   ├── google_sheets.py     # Інтеграція з Sheets (опційне дзеркало логів)
│   │   └── notifications.py     # Нагадування
│   ├── webapp/
│   │   ├── server.py            # aiohttp-додаток: Mini App сторінки + /api/*
│   │   ├── auth.py              # Спільний auth-декоратор для /api/* (initData)
│   │   └── templates/           # HTML Mini Apps (vanilla JS)
│   │       ├── nutrition.html   # /nutrition
│   │       ├── meal_entry.html  # /meal-entry
│   │       ├── profile.html     # /profile
│   │       ├── workout.html     # /workout — лог тренування
│   │       ├── statistics.html  # /statistics — статистика тренувань
│   │       └── chart.umd.min.js # Вендорений Chart.js (без CDN)
│   ├── database/
│   │   ├── models.py            # SQLAlchemy моделі (UUID)
│   │   ├── repository.py        # Репозиторії
│   │   └── session.py           # Сесії БД
│   ├── utils/
│   │   └── datetime_utils.py    # UTC/таймзона: utcnow, межі періодів/днів
│   ├── config.py                # Конфігурація (pydantic-settings)
│   └── main.py                  # Точка входу
├── tests/
├── docs/                        # Плани реалізації фіч (напр. статистика)
├── .env                         # Конфігурація (не в git!)
├── credentials.json             # Google API ключ (не в git!)
├── alembic.ini                  # Alembic конфігурація
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml               # Залежності проекту
├── ALEMBIC_QUICKSTART.md        # Швидкий старт з Alembic
└── README.md
```

## База даних

### Структура таблиць

Бот підтримує SQLite та PostgreSQL. Всі користувачі мають UUID ідентифікатори.

#### Таблиці

- **users** — основна інформація про користувачів
  - `id` (UUID, PK) — унікальний ідентифікатор
  - `telegram_id` (BigInteger, unique) — Telegram ID
  - `username`, `first_name`, `last_name`, `phone` — дані профілю Telegram
  - `is_admin`, `is_active`, `notifications_enabled` (Boolean)
  - `sync_workout_to_sheets` (Boolean) — чи дзеркалити лог тренувань у Sheets
    (за замовчуванням вимкнено, БД — основне сховище)
  - `created_at`, `updated_at` (DateTime)

- **profiles** — тіло й цілі по БЖУ (1-to-1 з users)
  - `id` (UUID, PK), `user_id` (UUID, FK → users.id, unique)
  - `age` (Integer), `height`, `weight` (Float), `gender` (String)
  - `daily_water_ml`, `daily_calories`, `daily_protein`, `daily_fats`,
    `daily_carbs` (Integer) — денні норми

- **trainings** — тренування (розклад для запису)
  - `id` (Integer, PK), `title`, `description`, `training_type` (String)
  - `scheduled_at` (DateTime, indexed), `duration_minutes`, `max_participants`
  - `location` (String), `is_cancelled` (Boolean)
  - `google_calendar_event_id` (String)
  - `created_at`, `updated_at`

- **bookings** — записи на тренування
  - `id` (Integer, PK)
  - `user_id` (UUID, FK → users.id), `training_id` (Integer, FK → trainings.id)
  - `status` (String: confirmed/cancelled/attended/no_show)
  - `reminder_24h_sent`, `reminder_2h_sent` (Boolean)
  - `created_at`, `updated_at`

- **daily_nutrition** — щоденний трекінг харчування (по записах, не одна сума на день)
  - `id` (Integer, PK), `user_id` (UUID, FK → users.id, indexed)
  - `date` (DateTime, indexed) — час запису
  - `water_ml`, `calories`, `protein`, `fats`, `carbs` (Integer)
  - `created_at`, `updated_at`

- **workout_sessions** — одне тренування (одне відвідування залу)
  - `id` (Integer, PK), `user_id` (UUID, FK → users.id, indexed)
  - `day` (Integer), `muscle_group` (String) — день програми / група м'язів
  - `duration_seconds` (Integer)
  - `performed_at` (DateTime UTC, indexed) — час початку тренування
  - `completed_at` (DateTime, nullable) — `NULL`, поки тренування в процесі
    (чернетка, GYM-2c); статистика враховує лише сесії із заповненим полем
  - `created_at`
  - Індекс: `(user_id, performed_at)`

- **workout_sets** — один підхід у межах сесії
  - `id` (Integer, PK), `session_id` (Integer, FK → workout_sessions.id, indexed)
  - `user_id` (UUID, FK → users.id, indexed) — денормалізовано для швидких вибірок
  - `exercise_name`, `muscle_group` (String), `set_number` (Integer)
  - `weight` (Float), `reps` (Integer), `planned_sets_reps` (String)
  - `performed_at` (DateTime UTC, indexed) — дубль з сесії, для фільтрів без join
  - `created_at`
  - Індекс: `(user_id, exercise_name, performed_at)`

### Міграції

Використовуйте Alembic для управління схемою:

```bash
# Перевірити поточну версію
alembic current

# Застосувати міграції
alembic upgrade head

# Створити нову міграцію після зміни моделей
alembic revision --autogenerate -m "опис змін"

# Відкотити останню міграцію
alembic downgrade -1
```

Детальна документація: [ALEMBIC_QUICKSTART.md](ALEMBIC_QUICKSTART.md)

## Google Sheets структура

Бот автоматично створює та оновлює аркуші:

1. **Тренування** — список всіх тренувань з датами та кількістю місць
2. **Записи** — записи користувачів на тренування
3. **Відвідування** — журнал відвідувань з відмітками

## Troubleshooting

### Помилка: "Target database is not up to date"

Застосуйте міграції:

```bash
alembic upgrade head
```

### Помилка: "telegram_bot_token validation error"

Переконайтеся що у `.env` встановлено `TELEGRAM_BOT_TOKEN`

### Помилка при підключенні до PostgreSQL

1. Перевірте чи запущено PostgreSQL: `sudo systemctl status postgresql`
2. Перевірте DATABASE_URL у `.env`
3. Перевірте що користувач має права на базу даних

### Google API помилки

1. Переконайтеся що Service Account email додано до Calendar/Sheets
2. Перевірте що файл `credentials.json` існує
3. Перевірте що API увімкнені у Google Cloud Console

## Оновлення проекту

```bash
# Отримайте останні зміни
git pull origin master

# Оновіть залежності
pip install -e . --upgrade

# Застосуйте нові міграції
alembic upgrade head

# Перезапустіть бота
# Ctrl+C для зупинки, потім:
python -m src.main
```

## Документація

- [ALEMBIC_QUICKSTART.md](ALEMBIC_QUICKSTART.md) — Робота з міграціями
- [MIGRATION_USERS_PROFILES.md](MIGRATION_USERS_PROFILES.md) — Історія розділення таблиць
- [MIGRATION_TO_UUID.md](MIGRATION_TO_UUID.md) — Історія переходу на UUID
- [alembic/README.md](alembic/README.md) — Повна документація Alembic

## Ліцензія

MIT
