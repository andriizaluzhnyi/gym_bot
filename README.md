# Gym Bot 🏋️

Telegram бот для управління записами на тренування з синхронізацією Google Calendar та Google Sheets.

## Функціонал

- 📅 **Розклад тренувань** — перегляд доступних тренувань
- 📝 **Запис на тренування** — онлайн запис з перевіркою вільних місць
- 🔔 **Нагадування** — автоматичні нагадування за 24 години та 2 години
- 📊 **Google Calendar** — синхронізація тренувань з календарем
- 📋 **Google Sheets** — ведення таблиці записів та відвідувань
- 🍎 **Харчування** — трекінг калорій, білків, жирів та вуглеводів
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

### Для користувачів

- `/start` — Почати роботу з ботом
- `/help` — Допомога
- `/schedule` — Розклад тренувань
- `/my` — Мої записи
- `/profile` — Мій профіль
- `/nutrition` — Трекінг харчування

### Для адмінів

- `/admin` — Адмін-панель
- `➕ Додати тренування` — Створити нове тренування
- `📊 Статистика` — Переглянути статистику
- `👥 Користувачі` — Список користувачів

## Структура проекту

```plaintext
gym_bot/
├── alembic/                     # Міграції бази даних
│   ├── versions/                # Файли міграцій
│   ├── env.py                   # Alembic environment
│   └── README.md
├── scripts/                     # Допоміжні скрипти
│   ├── migrate.py               # Helper для міграцій
│   └── migrate_*.py             # Застарілі ручні міграції
├── src/
│   ├── bot/
│   │   ├── handlers/
│   │   │   ├── start.py         # /start, /help
│   │   │   ├── schedule.py      # Розклад тренувань
│   │   │   ├── booking.py       # Запис/скасування
│   │   │   ├── nutrition.py     # Трекінг харчування
│   │   │   ├── profile.py       # Профіль користувача
│   │   │   ├── workout_program.py # Програми тренувань
│   │   │   └── admin.py         # Адмін функції
│   │   ├── keyboards.py         # Клавіатури
│   │   ├── calendar_picker.py   # Календар для вибору дати
│   │   └── bot.py               # Головний модуль бота
│   ├── services/
│   │   ├── google_calendar.py   # Інтеграція з Calendar
│   │   ├── google_sheets.py     # Інтеграція з Sheets
│   │   └── notifications.py     # Нагадування
│   ├── webapp/
│   │   ├── server.py            # Web додаток
│   │   └── templates/           # HTML шаблони
│   ├── database/
│   │   ├── models.py            # SQLAlchemy моделі (UUID)
│   │   ├── repository.py        # Репозиторії
│   │   └── session.py           # Сесії БД
│   ├── config.py                # Конфігурація (pydantic-settings)
│   └── main.py                  # Точка входу
├── tests/
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
  - `telegram_id` (Integer, unique) — Telegram ID
  - `username` (String) — Telegram username
  - `created_at` (DateTime) — дата реєстрації

- **profiles** — детальна інформація про користувачів (1-to-1 з users)
  - `id` (UUID, PK)
  - `user_id` (UUID, FK → users.id) — зв'язок з користувачем
  - `full_name` (String) — повне ім'я
  - `phone_number` (String) — телефон
  - `goal_calories`, `goal_protein`, `goal_fats`, `goal_carbs` — цілі по харчуванню

- **trainings** — тренування
  - `id` (Integer, PK)
  - `title` (String) — назва тренування
  - `date` (Date) — дата
  - `time` (Time) — час
  - `max_participants` (Integer) — ліміт місць
  - `calendar_event_id` (String) — Google Calendar Event ID

- **bookings** — записи на тренування
  - `id` (Integer, PK)
  - `user_id` (UUID, FK → users.id)
  - `training_id` (Integer, FK → trainings.id)
  - `booking_time` (DateTime) — час запису
  - `attended` (Boolean) — відмітка про відвідування

- **daily_nutrition** — щоденний трекінг харчування
  - `id` (Integer, PK)
  - `user_id` (UUID, FK → users.id)
  - `date` (Date) — дата
  - `calories`, `protein`, `fats`, `carbs` — спожиті нутрієнти
  - `notes` (Text) — нотатки

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
