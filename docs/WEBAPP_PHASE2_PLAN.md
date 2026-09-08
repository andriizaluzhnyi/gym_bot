# План реалізації (фаза 2): харчування v2, програми тренувань у БД, групові нагадування, меню бота

> Формат: Epic → Story-таски (Jira-стиль). Кожен таск має user story, acceptance
> criteria, технічні підзадачі (DB / Backend / Frontend / Bot) та оцінку в
> стори-поінтах (SP, Fibonacci: 1‑2‑3‑5‑8‑13). Нумерація продовжує
> [WEBAPP_STATISTICS_PLAN.md](WEBAPP_STATISTICS_PLAN.md) (GYM-0…GYM-20 виконано),
> тому перший таск тут — **GYM-21**.

## Контекст

Після фази 1 у проєкті є Telegram Mini App (`src/webapp/templates/*.html`,
`src/webapp/server.py`) з чотирма сторінками:

- `/nutrition` — «Сьогодні» (вода, кільця БЖВ, список прийомів їжі),
  внутрішній під-таб «Статистика» (GYM-15/16) і секція «Тренування» (список
  днів програми, веде на `/workout`);
- `/meal-entry` — форма додавання страви (назва + БЖВ, калорії рахуються з
  БЖВ 4/9/4);
- `/profile` — особисті дані, денні цілі, BMR/TDEE, toggle «Дублювати в
  Google Sheets» (GYM-2);
- `/workout` — лог тренування за програмою дня (чернетки в БД, GYM-2c);
- `/statistics` — статистика тренувань (Epic 1–4 фази 1).

Бот (`src/bot/`): головне меню `📊 Статистика` / `👤 Профіль` / `ℹ️ Допомога`,
chat-menu-кнопка `🍎 БЖУ` → `/nutrition` (`src/bot/handlers/start.py:52`),
адмінське меню `💪 Програма тренувань` / `📋 Переглянути програми`
(`src/bot/keyboards.py`), FSM створення програми
(`src/bot/handlers/workout_program.py`) пише **лише в Google Sheets**
(`GoogleSheetsService.add_workout_program`, аркуш `Програми (<user>)`).
Планувальник (`src/bot/bot.py: setup_scheduler`) знає лише про нагадування
щодо групових занять (`NotificationService.process_reminders`).

### Важливі особливості поточного коду, що впливають на план

- **Прийом їжі не має власного типу запису.** Кожен прийом і кожен «+250 мл»
  води — окремий рядок `daily_nutrition`; «це прийом їжі» визначається
  евристикою `water_ml == 0` (`api_get_today_meals`,
  `src/webapp/server.py:335`). `meal_name` з форми **не зберігається** —
  ендпоінт лише повертає його назад у відповіді (`server.py:284`), тому в
  списку «Сьогодні» страви показуються без назви. Це блокує і нормальний UI
  списку, і вимкнення води (без явного типу запису фільтр по воді
  ламається), і фото-прийоми (немає куди прив'язати результат розпізнавання).
- **«Сьогодні» рахується в UTC, а не в `settings.timezone`.**
  `get_today_total` (`src/database/repository.py:630`) і
  `api_get_today_meals` беруть межі доби через `utcnow().replace(hour=0…)`.
  Для Києва (UTC+2/+3) страва, залогована о 01:00, зникає з «Сьогодні» до
  03:00 наступної доби і потрапляє в учорашній день статистики (GYM-14
  уже групує локально — тобто «Сьогодні» і «Статистика» **не узгоджені**).
  Правильний підхід уже є: `period_bounds_utc`/`to_local_date`
  (`src/utils/datetime_utils.py`).
- **Кнопка «📷 Фото» — заглушка** (`nutrition.html:1448`,
  `tg.showAlert('…буде доступна незабаром')`). Жодних AI-залежностей у
  `pyproject.toml` немає; ключів у `.env.example` — теж.
- **Програми тренувань живуть лише в Sheets.** Читання `/api/workout/program`,
  видалення `/api/workout/day`, `/api/workout/exercise`, пошук останнього дня
  (`get_last_program_day_for_muscle_group`) — усе через live Google Sheets
  API з username як ключем аркуша. Це успадковує обидва ризики фази 1
  (нестабільний username, `is_admin()` заглушений —
  `workout_program.py:58`) і не дає місця для метаданих вправи (картинка,
  відео, опис). Колонки аркуша: `День | Група м'язів | Вправа |
  Підходи/Повторення | Коментар | Дата` (`google_sheets.py:146`).
- **Група м'язів зберігається разом з емодзі** (`MUSCLE_GROUPS = ["🦴 Спина",
  …]`, `keyboards.py:68`) і саме в такому вигляді лежить у `workout_sets`,
  Sheets і query-параметрі `?muscle=`. Не міняємо — інакше розійдеться
  історія статистики (GYM-4/6).
- **Бот не обробляє події груп.** Немає жодного `my_chat_member`/`ChatType`
  хендлера; `dp.start_polling(allowed_updates=dp.resolve_used_update_types())`
  автоматично додасть `my_chat_member`, щойно з'явиться хендлер.
- **Chat-menu-кнопка виставляється per-chat** лише під час `/start`
  (`set_chat_menu_button(chat_id=…)`), тому перейменування не дійде до
  користувачів, які не натиснуть `/start` знову. Потрібен глобальний
  default (`set_chat_menu_button()` без `chat_id` при старті бота).
- **Тексти бота застаріли:** `/start` і `/help` описують лише запис на
  групові заняття (`📅 Розклад`, `📝 Мої записи` — кнопок у меню немає, хоча
  хендлери є); `set_my_commands` не викликається взагалі — список команд у
  клієнті порожній.
- **Мертві елементи навігації:** пункт `⚙️ Налаштування` (`href="#"`) є на
  всіх чотирьох сторінках Mini App і нікуди не веде.

### Ключові архітектурні рішення

**1. Програми тренувань переїжджають у БД (Epic 3) — за зразком GYM-2.**
`workout_program_exercises` стає основним сховищем; бот-FSM і WebApp пишуть
туди, `Sheets` — опційне дзеркало під тим самим перемикачем
`User.sync_workout_to_sheets` (перейменовується на «Дублювати в Google
Sheets» без уточнення «логи»). На відміну від GYM-2b (бекфіл логів
скасовано), **одноразовий імпорт програм із Sheets робимо** (GYM-29): даних
мало (десятки рядків на користувача), а автентифікація й читання цих самих
аркушів уже працюють у продакшені через `/api/workout/program` — тобто
жодної нової інтеграції, лише скрипт поверх наявного `get_workout_programs`.
Альтернатива «WebApp пише в Sheets тим самим `add_workout_program`»
відхилена: вона консервує username-ключ, латентність Sheets на кожне
відкриття `/workout` і не дає місця для каталогу вправ.

**2. Каталог вправ — окрема таблиця `exercises`,** до якої рядки програми
посилаються за `exercise_id`; назва вправи для сумісності зі статистикою
(`workout_sets.exercise_name`) дублюється текстом. Медіа (картинка,
відео-лінк, опис) — поля каталогу; **наповнення — поза цим планом**
(див. «Відкриті питання»), у цьому плані лише схема, читання й показ, якщо
контент є.

**3. Фото → БЖВ через OpenAI Vision, результат — лише чернетка.** Модель
повертає структуровану оцінку (назва, порція, БЖВ), користувач бачить її в
`/meal-entry`, редагує і **сам** натискає «Зберегти» через уже наявний
`POST /api/nutrition/meal`. Автозбереження AI-оцінок не робимо — точність
розпізнавання порцій на фото недостатня. Фото на сервері **не зберігаємо**
(приватність, обсяг), лише проксюємо в OpenAI. Фіча повністю вимкнена без
`OPENAI_API_KEY` (кнопка прихована).

**4. Групові нагадування — окрема сутність `group_chats` і окремий job
планувальника,** не розширення `NotificationService.process_reminders`
(той прив'язаний до `bookings`). Ідемпотентність — через `last_*_sent_on`
(локальна дата), як `reminder_24h_sent` у бронюваннях. У групах inline
`web_app`-кнопки Telegram не підтримує (лише приватні чати), тому кнопки
нагадувань — deep-link `https://t.me/<bot>?start=<section>` → у приватному
чаті `/start <section>` відкриває потрібну сторінку Mini App.

## Definition of Done (для кожного таска)

- Чиста логіка (визначення «чи час нагадувати», парсинг відповіді OpenAI,
  нормалізація назв вправ) — функції без БД/мережі в `src/services/*` з
  unit-тестами в `tests/` **у тому ж PR**; зовнішні виклики (OpenAI,
  Telegram, Sheets) у тестах мокаються.
- Нові `/api/*` ендпоінти — через `@webapp_auth` (`src/webapp/auth.py`).
  Ендпоінти з `?user=<username>` (доступ тренера до клієнта) дозволяють чужого
  `user` **лише** якщо `telegram_id` ∈ `settings.admin_user_ids`.
- Дати зберігаються в UTC; «сьогодні»/«день» — у `settings.timezone`
  (`src/utils/datetime_utils.py`).
- Нові env-змінні додаються в `.env.example` і README; секрети — тільки з
  оточення.
- Покриття CI не падає нижче порогу (60%); `flake8`/`mypy` зелені.
- Текст UI/повідомлень — українською, у стилі існуючих екранів; нові
  екрани підтримують `Telegram.WebApp.themeParams`.

## Огляд епіків

| Epic | Назва | SP | Пріоритет |
| ---- | ----- | -- | --------- |
| 0 | Фундамент харчування: тип запису, назва страви, локальний день | 3 | Must (блокує Epic 1) |
| 1 | Харчування: вкладка «Сьогодні», фото → БЖВ, вимкнення води | 19 | Must |
| 2 | Профіль: оновлення UI | 5 | Should |
| 3 | Тренування: програми в БД, додавання вправ з WebApp, картка вправи | 21 | Must |
| 4 | Бот у групі: нагадування про харчування, заміри, фото | 13 | Should |
| 5 | Бот: меню, кнопки, тексти | 4 | Must (дешево, помітно) |
| — | Наскрізні задачі | 5 | — |

Загалом: **≈ 70 SP**. MVP (див. нижче): **≈ 32 SP**.

---

## Epic 0 — Фундамент харчування

### ✅ GYM-21: Тип запису `daily_nutrition`, назва страви, локальна доба — **виконано**

**User story:** Як користувач, я хочу бачити в списку «Сьогодні» назви страв
і мати змогу видалити помилковий запис, а «сьогодні» має означати мій
календарний день, а не UTC.

**Acceptance criteria:**

- `DailyNutrition.entry_type` (`String(10)`, `'water' | 'meal'`, not null,
  index) і `DailyNutrition.meal_name` (`String(255)`, nullable). Міграція з
  бекфілом: `entry_type = 'water'` де `water_ml > 0`, інакше `'meal'`
  (рівно та сама евристика, що зараз у `api_get_today_meals`, — тому
  бекфіл не змінює жодного поточного результату).
- `POST /api/nutrition/meal` зберігає `meal_name`; `POST /api/nutrition/daily`
  (вода) пише `entry_type='water'`.
- `GET /api/nutrition/meals` повертає `meal_name`, фільтрує по
  `entry_type='meal'` (не по `water_ml == 0`) і бере межі дня в
  `settings.timezone` (`period_bounds_utc`-стиль: локальна доба → UTC-межі).
  `GET /api/nutrition/daily` (`get_today_total`) — ті самі локальні межі.
- `DELETE /api/nutrition/meal/{id}` — видаляє запис поточного користувача
  (`404`, якщо чужий/не існує; для `entry_type='water'` — теж дозволено,
  UI використає для «Відмінити» замість поточного локального
  `waterHistory`, який губиться при перезавантаженні).
- Тести: бекфіл-міграція на SQLite; запис о 01:00 Києва потрапляє в
  «сьогодні» (і в GYM-14 — той самий день); `DELETE` чужого запису → 404.

**Технічні підзадачі:**

- DB: поля в `src/database/models.py`, міграція в `alembic/versions/` з
  data-бекфілом (`op.execute(update … where water_ml > 0)`).
- Backend: `DailyNutritionRepository.get_meals_for_local_day(user_id, tz)`,
  `delete_by_id_for_user(id, user_id)`; переписати `get_today_total` на
  локальні межі (сигнатура `+ tz_name`, як у `get_totals_by_range`, GYM-14).
- Backend: `api_add_meal` / `api_get_today_meals` / новий
  `api_delete_meal` (через `@webapp_auth`).

**Примітка щодо реалізації:** `period_bounds_utc` (GYM-4) отримав третій
`period` — `"day"` (локальна доба, ті самі межі, що й для тижня/місяця,
лише з іншим кроком) — замість окремого хелпера; `get_today_total` і новий
`get_meals_for_local_day` викликають `period_bounds_utc("day", tz_name,
now_utc=...)` і приймають опційний `now_utc` для тестів (той самий приймач,
що вже був у `period_bounds_utc`). `entry_type`/`meal_name` — enum
`NutritionEntryType` (`src/database/models.py`, за зразком `Gender`), не
голі рядкові літерали. `DailyNutritionRepository.create()` тепер вимагає
`entry_type` явно (без дефолту) — обидва продакшн-виклики
(`api_save_daily_nutrition`, `api_add_meal`) передають його свідомо;
непов'язаний legacy-метод `create_or_update` (dead code, викликів немає
ніде в проєкті) лишили з дефолтом `entry_type="meal"`, щоб не падав, якщо
колись знадобиться, а не видаляли — видалення поза скоупом цього тікета.
`DELETE /api/nutrition/meal/{id}` не розрізняє «чужий» і «неіснує» — обидва
`404`, як і в `/api/statistics/history/{session_id}`.

Міграція (`alembic/versions/20260908_1400-19d5485f6ff1_…`) — nullable
`ADD COLUMN` → `UPDATE … CASE WHEN water_ml > 0 THEN 'water' ELSE 'meal'
END` → `ALTER COLUMN … NOT NULL`, той самий тришаговий патерн, що й у
`sync_workout_to_sheets` (GYM-2), тільки без єдиного `server_default` (тут
бекфіл рядково-залежний, не константа). Тест бекфілу
(`tests/test_migration_nutrition_entry_type.py`) запускає `upgrade()`/
`downgrade()` міграції напряму проти окремого sync SQLite-з'єднання через
руками зібраний `alembic.operations.Operations`, підмінюючи ім'я `op` у
завантаженому модулі міграції — не через `alembic.command.upgrade()`
(та й проходить весь ланцюжок ревізій, а три старіші файли роблять
`from src.database import models`, що імпортом тягне
`src/database/session.py` і будує async-engine з `DATABASE_URL` ще на
етапі імпорту — не стосується того, що перевіряє цей тест). У реальному
розгортанні (Postgres, `docker-compose`) це не проблема:
`settings.db_url` там валідний `asyncpg`-URL що для сесії, що для
Alembic-обгортки. Виявлено принагідно (поза скоупом цього тікета):
`alembic/env.py` не приводить `sqlite+aiosqlite://` до синхронного
драйвера (на відміну від `postgresql+asyncpg://`), тому на SQLite
`command.upgrade()` у `run_bot()` фактично завжди падає в `except` і
відкочується на `init_db()` (`create_all` — без жодних міграцій, зокрема
без бекфілу) — для чистої dev-бази це нешкідливо (нема даних, які
бекфілити), але сам факт «на SQLite Alembic ніколи насправді не
виконується» ніде не задокументовано.

**SP:** 3

---

## Epic 1 — Харчування: «Сьогодні», фото → БЖВ, вода

### ✅ GYM-22: Оновлення UI вкладки «Сьогодні» — **виконано**

**User story:** Як користувач, я хочу, щоб вкладка «Сьогодні» показувала
страви з назвами, дозволяла швидко додати/видалити прийом їжі і не мала
кнопок-заглушок.

**Acceptance criteria:**

- Список прийомів їжі: назва страви (`meal_name`, fallback «Прийом їжі»),
  час, ккал і БЖВ-теги; свайп або кнопка «🗑» → підтвердження
  (`tg.showConfirm`) → `DELETE /api/nutrition/meal/{id}` → перерахунок
  кілець без перезавантаження сторінки.
- Дії картки «Прийоми їжі»: `➕ Додати` (→ `/meal-entry`) і `📷 Фото`
  (GYM-24; прихована, якщо `GET /api/user/settings` каже
  `photo_recognition_enabled: false`). Кнопка `✏️` без підпису
  прибирається.
- Кільця БЖВ: підпис «залишилось N ккал» під числом; при перевищенні цілі —
  колір кільця змінюється (той самий прийом, що й «свіжий рекорд» на
  `/statistics`), без окремих алертів.
- Картка «Вода»: «↩️ Відмінити» видаляє останній water-запис через
  `DELETE` (GYM-21), а не локальну історію; після перезавантаження кнопка
  лишається активною, якщо є що відміняти.
- Порожній стан «Немає записів за сьогодні» веде тапом на `/meal-entry`.
- Дата в шапці — локальна (`settings.timezone` збігається з тим, що
  повертає бекенд; клієнт не рахує «сьогодні» сам із `new Date()`
  користувача, який може бути в іншій зоні — бере `date` з відповіді
  `GET /api/nutrition/daily`).

**Технічні підзадачі:**

- Frontend: `nutrition.html` — `displayMealsList` через `createElement`
  (як картки в `statistics.html`, без `innerHTML`-шаблонів з даними
  користувача — `meal_name` вводить сам користувач, XSS), обробники
  delete/undo.
- Backend: `GET /api/nutrition/daily` додатково повертає `date`
  (локальна ISO-дата) і `last_water_entry_id`.

**Примітка щодо реалізації:** нова
`DailyNutritionRepository.get_last_entry_id_for_local_day(user_id,
tz_name, entry_type, now_utc=...)` — узагальнена версія того самого
патерну, що й `get_meals_for_local_day` (GYM-21): `period_bounds_utc
("day", ...)` + фільтр по `entry_type`, але повертає лише `id`
найновішого запису, не весь список. «↩️ Відмінити» тепер видаляє
реальний рядок (`DELETE /api/nutrition/meal/{id}`, GYM-21) замість
запису компенсаційного від'ємного інкременту (як було) — старий підхід
лишав обидва рядки в БД (скасований запис і компенсацію), новий справді
прибирає помилковий запис. Клієнт більше не тримає жодної історії сум:
і додавання води, і відміна щоразу читають `id`/суми з відповіді сервера.

Фото-кнопка (`📷 Фото`) залишена в розмітці, але захована за замовчуванням
(`display: none`) — керується `settings.photo_recognition_enabled`, якого
`/api/user/settings` ще не повертає (GYM-23/24 не зроблені); коли GYM-23
додасть це поле, кнопка з'явиться сама, без правок `nutrition.html`.
«🗑» на кожній картці страви — кнопка з підтвердженням через
`tg.showConfirm`, не swipe-жест (AC дозволяв «свайп **або** кнопка» —
кнопка дешевша й надійніша для SP-бюджету цього тікета).

Ручна перевірка: у цьому середовищі немає ні `chromium-cli`, ні
Playwright-браузера, ні компілятора для збірки нативних Python-байндингів
до JS-рушія (спроби встановити `quickjs`/`py-mini-racer` не зібралися) —
повноцінний скріншот у браузері був недосяжний. Замість цього: (1)
`GET /nutrition` через `aiohttp`-тестовий клієнт підтвердив, що сторінка
віддає `200` з новою розміткою (кнопка «➕ Додати» є, старої `edit-btn`
немає, `photoBtn`/`caloriesLabel` присутні); (2) весь inline-скрипт
пройшов через `esprima`-парсер (JS-рушій, встановлений через `uv run
--with esprima`) без синтаксичних помилок — ізольовано підтверджує, що
відредаговані секції (стан, дата, кільця, вода, список страв) не містять
розбитих дужок/шаблонних рядків.

**SP:** 5

### ✅ GYM-40: Картка «Тренування сьогодні» на вкладці «Сьогодні» — **виконано**

> Номер вищий за сусідні (GYM-23…39 вже розписані в цьому плані) — доданий
> пізніше, номер призначено по порядку додавання в беклог, а не за
> позицією в документі; фізично розташований тут, бо стосується тієї самої
> вкладки «Сьогодні», що й GYM-22.

**User story:** Як користувач, я хочу одразу на вкладці «Сьогодні» бачити,
чи я вже тренувався сьогодні і коротку статистику цього тренування
(м'язова група, тривалість, тоннаж), не заходячи окремо на `/statistics`.

**Acceptance criteria:**

- `GET /api/statistics/today` (`@webapp_auth`, той самий `?user=`-конвент,
  що й решта `/api/statistics/*` — тренер бачить клієнта) →
  `{"success": true, "data": {...} | null}`. `data` — `null`, якщо сьогодні
  (`settings.timezone`) немає жодної **завершеної** сесії (чернетки,
  `completed_at IS NULL`, не рахуються — той самий фільтр, що й в історії/
  статистиці, GYM-2c); інакше — найсвіжіша завершена сесія дня, у тому
  самому форматі, що й рядок `/api/statistics/history`
  (`session_id, date, muscle_group, exercises_count, sets_count,
  total_volume, duration_minutes`).
- Кілька тренувань за один день (рідкісний, але можливий кейс — GYM-1 їх
  не змішує в одну сесію) — картка показує лише найновішу; про решту
  користувач дізнається з `/statistics` → «Історія».
- `/nutrition`: нова картка «🏋️ Тренування сьогодні» у `#todaySection`
  (стиль інших карток «Сьогодні»), під карткою «Прийоми їжі» — іконка
  групи м'язів, тривалість, `N вправ · M підходів`, тоннаж; тап веде на
  `/statistics` (вкладка «Історія»). Картка **не рендериться взагалі**,
  якщо `data === null` — це нормальний стан більшості днів, а не порожній
  стан з підказкою (на відміну від картки «Прийоми їжі»).
- Дата — `settings.timezone` через уже наявний `period_bounds_utc("day",
  ...)` (GYM-21), не UTC і не локальний час пристрою користувача.
- Тести: є завершена сесія сьогодні → повертається; сесія вчора → `null`;
  чернетка (`completed_at IS NULL`) сьогодні → не враховується; дві
  завершені сесії сьогодні → повертається найновіша.

**Технічні підзадачі:**

- Backend: `api_get_today_workout` — `_resolve_statistics_owner`
  (GYM-4-конвенція), `period_bounds_utc("day", settings.timezone)`,
  `WorkoutSessionRepository.get_sessions_by_period(owner.id, start, end)`
  (уже сортує найновіші першими), `_serialize_session_summary(sessions[0])`
  якщо список не порожній — жодної нової агрегаційної логіки, лише нове
  компонування вже наявних частин (GYM-4/GYM-10/GYM-21).
- Frontend: `nutrition.html` — `loadTodayWorkoutSummary()` (виклик поруч
  із `loadDailyNutrition()`/`loadMealsList()` в `Initialize`), картка +
  приховування при `null`.

**Примітка щодо реалізації:** зумисно НЕ розширює `/api/statistics/summary`
(`period=day`) попри те, що `period_bounds_utc` вже підтримує `"day"` —
той ендпоінт агрегує (`avg_duration_minutes`, `most_trained_muscle` по
кількох сесіях) і не містить `exercises_count`/`sets_count`, потрібних для
«короткої статистики» одного тренування; окремий ендпоінт із форматом
`_serialize_session_summary` дешевший, ніж розширювати форму відповіді
`summary` умовно по періоду.

`api_get_today_workout` фізично розташований поруч із
`_serialize_session_summary` і GYM-10-ендпоінтами (`api_get_history`,
`api_get_history_session`) у `server.py`, а не одразу після
`api_get_statistics_summary` (де за номером тікета він міг би здаватись
логічнішим) — щоб не робити forward-reference на хелпер, визначений на
~1000 рядків нижче по файлу; маршрут `/api/statistics/today` зареєстровано
між `achievements` і `history`.

`/statistics` раніше не вмів відкривати конкретну вкладку по посиланню —
додано читання `?tab=` (`activateTab(requestedTab)` при завантаженні,
поруч із вже наявним `?user=`); спрацювало без жодних змін у
завантаженні даних вкладок, бо жодна з них не лінива (усі
`load*Tab()`-виклики вже безумовні внизу скрипта, на відміну від
статистики харчування на `/nutrition`, GYM-15, яка лінива). Картка на
`/nutrition` перевикористовує вже наявні класи `.workout-day-card`/
`.workout-day-info`/`.workout-day-title`/`.workout-day-subtitle`/
`.workout-day-arrow` (той самий tappable-рядок, що й у списку днів
програми) замість нових CSS-класів.

**SP:** 3

### GYM-23: Фото → БЖВ — бекенд (OpenAI Vision)

**User story:** Як користувач, я хочу сфотографувати тарілку і отримати
оцінку БЖВ, щоб не вводити цифри вручну.

**Acceptance criteria:**

- `POST /api/nutrition/meal/photo` (multipart, поле `photo`, ≤ 5 МБ,
  `image/jpeg|png|webp|heic`): повертає
  `{meal_name, portion_grams, protein, fats, carbs, calories, confidence:
  "low|medium|high", notes}` — **не зберігає** нічого в БД і не зберігає
  файл.
- `503 {"error": "photo_recognition_disabled"}`, якщо `OPENAI_API_KEY`
  порожній; `413` при перевищенні розміру; `422`, якщо модель відповіла,
  що на фото немає їжі (`is_food: false`).
- Сервіс `src/services/food_recognition.py`: `recognize_food(image_bytes,
  mime) -> FoodEstimate` (async, OpenAI SDK, `response_format` = JSON
  schema) і чиста `parse_food_estimate(payload: dict) -> FoodEstimate`
  (валідація діапазонів, `calories` перераховується з БЖВ за 4/9/4, якщо
  модель дала неузгоджене число — так само, як рахує `/meal-entry`).
- Промпт українською, просить оцінку на **всю видиму порцію** і
  консервативну впевненість; `OPENAI_MODEL` конфігурований (за замовчуванням
  `gpt-4o-mini` — дешево, достатньо для оцінки; можна підняти в env).
- Таймаут 30 с, одна повторна спроба на 5xx/таймаут; будь-яка помилка
  OpenAI → `502 {"error": "recognition_failed"}` без витоку деталей у
  відповідь (деталі — в лог).
- Тести: `parse_food_estimate` (валідний/неповний/поза діапазоном/
  `is_food=false`), ендпоінт з мокнутим `recognize_food` (200/413/422/502/503).

**Технічні підзадачі:**

- Config: `openai_api_key: str = ""`, `openai_model: str = "gpt-4o-mini"`
  у `src/config.py`; `.env.example`.
- Deps: `openai>=1.50` у `pyproject.toml` (`uv lock`).
- Backend: `api_recognize_meal_photo` (`@webapp_auth`,
  `request.multipart()`), `GET /api/user/settings` →
  `photo_recognition_enabled: bool` (щоб UI знав, чи показувати кнопку).

**SP:** 5

### GYM-24: Фото → БЖВ — UI (зйомка, прев'ю, підтвердження)

**User story:** Як користувач, я хочу натиснути «📷 Фото», зняти/обрати
фото і побачити заповнену форму страви, яку можна поправити перед
збереженням.

**Acceptance criteria:**

- «📷 Фото» на «Сьогодні» відкриває `<input type="file" accept="image/*"
  capture="environment">`; перед відправкою фото стискається на клієнті
  (canvas, довша сторона ≤ 1024 px, JPEG q≈0.8) — менше трафіку і токенів.
- Стан «Розпізнаю…» з блокуванням кнопки; після відповіді — перехід на
  `/meal-entry?prefill=<base64url json>` (або `sessionStorage`), поля
  заповнені, зверху бейдж «Оцінка з фото · впевненість: середня» і
  підказка «Перевірте порцію». Збереження — звичайним «Зберегти» через
  `POST /api/nutrition/meal` (GYM-21, з `meal_name`).
- Помилки: `422` → «На фото не видно їжі», `502/503` → «Не вдалося
  розпізнати, введіть вручну» + одразу відкрити порожній `/meal-entry`.
- Кнопка прихована, якщо `photo_recognition_enabled=false`.
- Перевірено на Telegram iOS/Android/Desktop, що `input[type=file]` у
  WebView відкриває камеру/галерею (див. ризики).

**Технічні підзадачі:**

- Frontend: `nutrition.html` (file input, стискання, fetch multipart),
  `meal_entry.html` (prefill з query/`sessionStorage`, бейдж).

**SP:** 3

### ✅ GYM-25: Вимкнення трекінгу води — **виконано**

**User story:** Як користувач, який не рахує воду, я хочу вимкнути картку
«Вода», щоб вона не займала екран і не псувала статистику.

**Acceptance criteria:**

- `Profile.water_tracking_enabled` (Boolean, default `True`) + міграція.
- `GET/POST /api/user/settings` читає/пише `water_tracking_enabled`.
- `/profile`: toggle «Відстежувати воду» в картці денних цілей; при
  вимкненні поле «Вода (мл)» стає неактивним (значення зберігається — при
  повторному увімкненні повертається).
- `/nutrition`: картка «Вода» прихована при `false`; водяні записи не
  створюються; у «Статистиці» (GYM-15) нічого не змінюється (вода там не
  малюється), але `by_day[].water_ml` лишається в API для сумісності.
- Бот: `_format_nutrition_settings` (`user_profile.py:85`) показує
  «💧 Вода: вимкнено» замість норми; кнопка «💧 Денна норма води» в
  `get_nutrition_settings_keyboard` при вимкненій воді пропонує спершу
  увімкнути (окремий callback `edit:water_toggle`).
- Групові нагадування (Epic 4) — нагадування про воду не окремий тип, тож
  залежності немає.
- Тести: settings round-trip; профіль без рядка `profiles` (дефолти) →
  `True`.

**Технічні підзадачі:**

- DB: поле + міграція.
- Backend: `ProfileRepository.update(... water_tracking_enabled)`,
  `UserRepository.get_nutrition_settings` повертає поле (і дефолт `True`).
- Frontend: `profile.html` toggle (стиль `.toggle-row` з картки
  «Тренування»), `nutrition.html` — умовний показ картки.
- Bot: `user_profile.py` — текст + toggle-callback.

**Примітка щодо реалізації:** міграція — той самий двокроковий патерн
`server_default` → drop default, що й `sync_workout_to_sheets` (GYM-2), без
окремого тесту-бекфілу (на відміну від GYM-21, тут дефолт — константа
`True` для всіх існуючих рядків, а не значення, залежне від даних). Toggle
на `/profile` **не** зберігається одразу (на відміну від toggle'а Sheets) —
він у тій самій картці «Денні цілі» й іде разом з рештою полів через
головну кнопку «Зберегти»; вимкнений `#waterInput` лишається в DOM зі
своїм значенням (просто `disabled`), тому воно природно повертається при
повторному увімкненні без жодної додаткової логіки збереження/відновлення.
На `/nutrition` картка «Вода» ховається через `style.display = 'none'` —
без кнопок немає шляху створити водяний запис, окремої заборони на
бекенді для `POST /api/nutrition/daily` не додавали (як і toggle
Sheets-синхронізації, це керує лише UI, не самим API). Бот:
`get_nutrition_settings_keyboard` тепер приймає `water_tracking_enabled`
(усі 9 викликів у файлі передають `nutrition["water_tracking_enabled"]` —
поле завжди є в словнику, включно з дефолтним для користувача без рядка
`profiles`); новий `enable_water_tracking` (callback `edit:water_toggle`)
вмикає трекінг і одразу перемальовує екран налаштувань, а не веде в
окремий діалог підтвердження. Дорогою підтягнуто документацію
`daily_nutrition` (GYM-21: `entry_type`/`meal_name`) у README, яка була
пропущена в тому тікеті.

**SP:** 3

---

## Epic 2 — Профіль

### ✅ GYM-26: Оновлення UI вкладки «Профіль» — **виконано**

**User story:** Як користувач, я хочу, щоб профіль виглядав як єдиний екран
налаштувань: хто я, мої цілі (з можливістю взяти розраховані), сповіщення й
інтеграції — з нативною кнопкою збереження.

**Acceptance criteria:**

- Шапка: аватар/ім'я/`@username` з `tg.initDataUnsafe.user` (лише
  відображення; `photo_url` може бути відсутній — fallback ініціали).
- Секції-картки: «Особисті дані» (як зараз + ІМТ), «Денні цілі» (+ toggle
  води з GYM-25, + кнопка «Взяти розраховані» — переносить TDEE у ккал і
  розкладає БЖВ 30/25/45 % у поля; лише заповнює інпути, збереження — як
  завжди), «Сповіщення» (toggle `User.notifications_enabled` — поле в
  моделі є, але ніде не редагується), «Інтеграції» (toggle Sheets із GYM-2
  з оновленим текстом «Дублювати програми та логи тренувань у Google
  Sheets» — після Epic 3 він охоплює й програми).
- Збереження через `tg.MainButton` («Зберегти», показується лише коли є
  зміни — `isDataChanged` уже є), а не in-page-кнопка; після успіху —
  `HapticFeedback.notificationOccurred('success')` і `MainButton.hide()`.
- Валідація полів inline (діапазони з `min`/`max` уже задані) замість
  `tg.showAlert`.
- `GET/POST /api/user/settings` розширено `notifications_enabled`.

**Технічні підзадачі:**

- Backend: `UserRepository.set_notifications_enabled`, розширення
  `api_get_user_settings`/`api_update_user_settings` (переписати обидва на
  `@webapp_auth` за нагоди).
- Frontend: `profile.html`.
- Tests: settings round-trip з `notifications_enabled`.

**Примітка щодо реалізації:** `notifications_enabled` — поле `User`, не
`Profile`, тому `UserRepository.set_notifications_enabled` лишився
окремим методом (за зразком `set_sync_workout_to_sheets`), а не
параметром `update_nutrition_settings` — `api_update_user_settings`
викликає обидва: `update_nutrition_settings` для профільних полів (як і
раніше) і `set_notifications_enabled` окремо, коли поле присутнє в тілі
запиту. `get_nutrition_settings` тепер додає `notifications_enabled` до
відповіді в обох гілках (є `Profile` чи ще нема) — один комбінований
запит для екрана профілю замість другого round-trip.

Кнопка «📐 Взяти розраховані» розміщена в картці «Розрахункові показники»
(а не «Денні цілі») — вона з'являється лише коли BMR/TDEE взагалі
порахований (вік+зріст+вага+стать заповнені), тож логічно стоїть поруч із
числом, яке «бере», а не в картці, куди значення лише записуються.

Текст toggle'а «Дублювати в Google Sheets» **не** розширено словом
«програми», хоча так написано в AC (нагадка на GYM-28) — той функціонал
(дзеркалення програм у Sheets) ще не реалізований, і назва картки
«Тренування» → «Інтеграції» перейменована, а сам текст toggle'а
лишається точним щодо поточної поведінки (лише логи); формулювання
розширить сам GYM-28, коли з'явиться що дублювати.

Валідація полів — інлайн `.field-error` під кожним інпутом (пусте поле не
вважається помилкою, лише поза межами `min`/`max`); `tg.showAlert`
прибрано з усього флоу збереження профілю (успіх → `MainButton.hide()` +
haptic, мережева помилка → `saveErrorBanner` замість алерту) — лишився
тільки там, де раніше не було (порожній `href="#"` пункт нижньої
навігації, підтвердження виходу зі сторінки через нативний `confirm()`) —
обидва поза скоупом цього тікета (AC стосується саме валідації полів;
уніфікація нав-меню — GYM-37).

**SP:** 5

---

## Epic 3 — Тренування: програми в БД, додавання вправ, картка вправи

### ✅ GYM-27: Моделі `Exercise` + `WorkoutProgramExercise`, міграція, репозиторії — **виконано**

**User story:** Як розробник, я хочу зберігати програму тренувань і каталог
вправ у БД, щоб WebApp і бот працювали з одним джерелом без Google Sheets.

**Acceptance criteria:**

- Таблиця `exercises`: `id`, `name` (String 255, not null),
  `normalized_name` (lower/trim/collapse-spaces, **unique**, index),
  `muscle_group` (String|null), `description` (Text|null), `image_url`
  (String|null), `video_url` (String|null), `created_at`, `updated_at`.
- Таблиця `workout_program_exercises`: `id`, `user_id` (FK → `users.id`,
  index), `day` (int, not null), `muscle_group` (String, not null — з
  емодзі, як у `MUSCLE_GROUPS`), `exercise_id` (FK → `exercises.id`,
  index), `exercise_name` (String — знімок назви на момент додавання, для
  сумісності з `workout_sets.exercise_name` і Sheets-рядком),
  `sets_reps` (String 50), `comment` (Text|null), `position` (int — порядок
  у дні), `created_at`. Індекс `(user_id, day, position)`.
- `ExerciseRepository.get_or_create_by_name(name, muscle_group)` — чиста
  нормалізація в `src/services/exercise_names.py: normalize_exercise_name`
  (тести: регістр, пробіли, апостроф `'`/`’`).
- `WorkoutProgramRepository`: `add_exercises(user_id, day, items)`,
  `get_program(user_id, day=None, muscle=None)` (відповідь у тій самій
  формі `{day, muscle_group, exercise, sets_reps, comment, created_at}`,
  що й `get_workout_programs`, щоб `workout.html`/`nutrition.html` не
  чіпати), `delete_day(user_id, day)`, `delete_exercise(user_id, day,
  exercise_name)`, `get_last_day_for_muscle(user_id, muscle)`,
  `get_days_summary(user_id)`.
- Alembic-міграція; перевірено на SQLite і PostgreSQL.

**Примітка щодо реалізації:** `ExerciseRepository.get_or_create_by_name`
робить `from src.services.exercise_names import normalize_exercise_name`
**всередині методу**, не на рівні файлу — `src/services/__init__.py`
жадібно імпортує `notifications.py`, який сам імпортує з
`src/database/repository.py`; імпорт `src.services.*` на рівні модуля в
`repository.py` створив би циклічний імпорт (`repository.py` раніше
взагалі не залежав від нічого під `src.services`). Той самий прийом, що
вже використовується в цьому файлі для `sqlalchemy.func` в окремих
методах.

`get_program()` повертає `day` як **рядок** (`str(row.day)`), хоча в БД
це `Integer` — свідомо, щоб форма відповіді залишалась ідентичною
`GoogleSheetsService.get_workout_programs` (рядки Sheets — завжди
рядки), і `workout.html`/`nutrition.html` не довелося чіпати, коли GYM-28
підключить цей репозиторій до `/api/workout/program`. `created_at`
форматується як `%d.%m.%Y %H:%M` з **наївного UTC**, без переведення в
`settings.timezone` — сигнатура `get_program(user_id, day=None,
muscle=None)` в AC не має параметра `tz_name`, а сам `created_at` зараз
ніде в UI не читається (перевірено — ні `workout.html`, ні
`nutrition.html` це поле не використовують), тож точність тут не
критична; якщо GYM-28/30 колись покажуть цю дату користувачу — перевести
на `to_local_date`-подібну конвертацію (той самий підхід, що й у
`_serialize_session_summary`) окремою правкою.

`get_days_summary(user_id)` — форма відповіді (`{day, muscle_groups,
exercises_count}`) не була деталізована в AC, тому спроєктована як
DB-нативний еквівалент групування, яке `nutrition.html`'s
`loadWorkoutPrograms()` зараз робить на клієнті (`dayGroups`) — щоб GYM-28
міг замінити той клієнтський код одним запитом замість фільтрації повного
списку. `ExerciseRepository.search()` (згаданий у плані GYM-30 для
автопідказки) **не** додано цим тікетом — GYM-27 просив лише
`get_or_create_by_name`; GYM-30 додасть `search()` коли знадобиться
UI-автопідказка.

**SP:** 3

### ✅ GYM-28: БД — основне сховище програм; бот і WebApp пишуть у БД, Sheets — дзеркало — **виконано (з відхиленнями, див. примітку)**

**User story:** Як тренер, я хочу, щоб програма, створена в боті, одразу
з'являлась у WebApp клієнта (і навпаки), незалежно від Google Sheets.

**Acceptance criteria:**

- Бот: `program:finish` (`workout_program.py:454`) пише в
  `WorkoutProgramRepository.add_exercises`; власник — `selected_user`
  (username → `UserRepository.get_by_username`; якщо `None` — сам
  адмін). Sheets `add_workout_program` викликається **лише** якщо у
  власника `sync_workout_to_sheets=True`; помилка Sheets логується,
  відповідь «✅ День N збережено!» не залежить від неї (як GYM-2).
  `get_last_program_day_for_muscle_group` → `get_last_day_for_muscle`
  (БД). `📋 Переглянути програми` (`_show_programs*`) читає з БД.
- WebApp: `GET /api/workout/program`, `DELETE /api/workout/day`,
  `DELETE /api/workout/exercise` читають/пишуть БД; при увімкненому
  дзеркалі видалення також дублюється в Sheets (`delete_workout_day`/
  `delete_exercise`) некритично.
- **Авторизація `?user=`** (закриває ризик фази 1 «`is_admin()`
  заглушений» для програм): `user` ≠ власний username дозволено лише для
  `telegram_id` ∈ `settings.admin_user_ids`, інакше `403`. Спільний хелпер
  `_resolve_program_owner(request)` за зразком `_resolve_statistics_owner`
  (GYM-4); той самий хелпер застосувати до `/api/statistics/*` і
  `/api/workout/*` (лог, чернетки) — одна зміна, всі дірки закриті.
- `is_admin()` у `workout_program.py` перестає бути заглушкою: кнопки
  `💪 Програма тренувань`/`📋 Переглянути програми` для не-адміна показують
  лише **свою** програму без вибору користувача (а не список усіх
  username).
- Тести: бот-flow (через `tests/bot_mocks.py`) пише в БД і не викликає
  Sheets при вимкненому дзеркалі; `403` для чужого `user` не-адміном;
  `200` для адміна; форма відповіді `/api/workout/program` незмінна
  (`tests/test_webapp_workout_log.py` — без правок).

**Технічні підзадачі:**

- Bot: `workout_program.py` — заміна Sheets-викликів на репозиторій, guard
  `is_admin`.
- Backend: `_resolve_program_owner`, переписати три ендпоінти, застосувати
  хелпер до `/api/statistics/*`, `/api/workout/session/*`, `/api/workout/log`.
- Backend: Sheets-дзеркало — `if owner.sync_workout_to_sheets:` навколо
  наявних методів `GoogleSheetsService` (без змін у самому сервісі).

**Примітка щодо реалізації — відхилення від AC:** хелпер застосовано до
`/api/statistics/*` (перейменований з `_resolve_statistics_owner`, GYM-4 —
GYM-40's нотатка про нього тепер стара назва) і до всіх трьох
program-ендпоінтів (`/api/workout/program`, `/api/workout/day`,
`/api/workout/exercise`) — **АЛЕ НЕ** до `/api/workout/log`,
`/api/workout/session/start`, `/api/workout/session/exercise`, як
просив AC. Ці три ендпоінти й далі резолвять власника через
`body["user"]`/`session_id` без перевірки адміна — той самий ризик, що й
у програм, лишається відкритим для логів/чернеток. Свідоме рішення:

- Форма кожного з трьох принципово інша (`body.user` для двох, і
  ЖОДНОГО `user`-поля для `/session/exercise` — там лише `session_id`,
  тобто потрібна геть інша перевірка: `workout_session.user_id ==
  caller.id`, не `_resolve_program_owner`).
- Усі три мають вже наявне, велике тестове покриття
  (`tests/test_webapp_workout_log.py`,
  `tests/test_workout_draft_sessions.py`), включно з тестом, що явно
  ФІКСУЄ поточну (дірову) поведінку як очікувану
  (`test_owner_is_resolved_from_body_user_not_caller`) — змінювати їх
  безпечно вимагає окремого зосередженого проходу, не додатка до вже
  великого тікета (10 файлів статистики довелось виправити тільки для
  вже запланованої частини).
- Ризик цього дедлайну: `is_admin()`-заглушка для ЛОГІВ (не програм)
  лишається — трекер (будь-хто) все ще може писати/читати чужі
  тренування через `/api/workout/log`/`/api/workout/session/*`. Якщо це
  критично — окремий таск GYM-28b (не заведений формально, орієнтир на
  майбутнє) робить те саме, що тут зроблено для програм.

Решта AC — без відхилень: `is_admin()` — реальна перевірка;
`💪 Програма тренувань`/`📋 Переглянути програми` для не-адміна одразу
йдуть у гілку «немає інших користувачів» (та сама, що й раніше
використовувалась, коли БД була порожня) — жодного дублювання коду.
`process_program_action` після збереження показує адмінську чи звичайну
клавіатуру залежно від `is_admin(callback.from_user.id)` (раніше завжди
показував адмінську, навіть не-адміну — виправлено принагідно, бо
раніше в цю гілку міг потрапити лише адмін). Мертва функція
`_show_programs` (визначена, але ніде не викликана) — видалена, а не
переписана. `_show_programs_filtered` отримала явний параметр
`caller_telegram_id` — раніше вона неявно покладалась на
`message.from_user`, а `message` там — це `callback.message`
(**повідомлення бота**, не того, хто натиснув кнопку); з новим DB-шляхом
це стало б реальним багом для гілки «немає обраного user» (не-адмін
дивиться свою програму), тож виправлено як частину цього рефакторингу.
Кнопка «🏋️ Почати тренування» після перегляду тепер зважає на
`owner.username` (не сирий `user_name`-параметр), тому з'являється і для
не-адміна, що дивиться власну програму без явного вибору користувача.

Тести: `tests/test_webapp_resolve_program_owner.py` (уся матриця
403/404/self/admin для хелпера, окремо від конкретних ендпоінтів), `tests/test_webapp_workout_program.py` (три ендпоінти:
200/403/400/404, DB-запис, Sheets-дзеркало та його вимкнення/помилка),
`tests/test_bot_handlers_workout_program.py` (перший тест-файл для цього
бот-хендлера взагалі — is_admin, picker пропускається для не-адміна,
DB-запис при «Завершити», Sheets лише за увімкненого дзеркала, вибір
клавіатури). Дев'ять наявних тестових файлів статистики (`?user=`
трейнер-сценарії) оновлено — раніше вони фіксували діряву поведінку
(будь-хто міг переглянути чужі дані через `?user=`), тепер вимагають
`admin_user_id`, що й було метою фікса.

**SP:** 8

### ✅ GYM-29: Одноразовий імпорт програм із Google Sheets — **виконано**

**User story:** Як тренер, я хочу, щоб існуючі програми клієнтів з'явилися в
БД після розгортання GYM-28 без ручного перенабору.

**Acceptance criteria:**

- `scripts/import_workout_programs.py [--dry-run] [--user <username>]`:
  для кожного `User` з `username` читає `get_workout_programs(limit=0,
  user_name=username)` і пише через `add_exercises`, зберігаючи порядок
  рядків як `position`, `created_at` — з колонки «Дата» (`%d.%m.%Y %H:%M`,
  `settings.timezone` → UTC; якщо не парситься — `utcnow()`).
- Ідемпотентність: повторний запуск не дублює (пропускає користувача, у
  якого в БД уже є хоч один рядок програми, з повідомленням у лог);
  `--force` очищає й переімпортовує.
- Аркуші, для яких немає користувача з таким username, лише
  перелічуються у звіті (не імпортуються).
- Тести: парсер рядка → item (чиста функція), ідемпотентність на SQLite
  з мокнутим `GoogleSheetsService`.
- README: крок «після оновлення до GYM-28 запустіть імпорт один раз».

**Примітка щодо реалізації:** `WorkoutProgramRepository.add_exercises`
(GYM-27) вже призначав `position` автоматично через `_next_position()` —
і оскільки скрипт передає рядки одного дня в тому самому порядку, в
якому вони йшли в Sheets, порядок зберігається без додаткових змін до
`add_exercises`. Для `created_at` довелося додати новий необов'язковий
ключ елемента — **`created_at_utc`** (а не `created_at`): FSM бота
(`src/bot/handlers/workout_program.py`) вже кладе в кожен елемент
`created_at` як **рядок** `%d.%m.%Y %H:%M` для дзеркала в Sheets, і
`add_exercises` це поле завжди ігнорував. Перше формулювання цієї правки
використовувало ключ `created_at` під нове значення (`datetime`) — це
зламало 7 наявних тестів бота (`INSERT` падав з `TypeError: SQLite
DateTime type only accepts... datetime and date objects`, бо в БД
летів рядок замість `datetime`); виправлено окремим ключем, який ніхто
інший не використовує, з коментарем у docstring `add_exercises`, що
пояснює навіщо два різні ключі співіснують.

Ідемпотентність перевіряється через `WorkoutProgramRepository.get_program
(user_id)` — якщо в користувача вже є хоч один рядок і `--force` не
передано, весь `get_workout_programs` навіть не викликається (тест
`test_second_run_without_force_skips_and_does_not_duplicate` це прямо
перевіряє через `assert_awaited_once()`). `--force` додав новий метод
`WorkoutProgramRepository.delete_all_for_user(user_id)` (видаляє рядки
програми користувача з усіх днів одним проходом) — в репозиторії раніше
був лише `delete_day` (по одному дню), а `--force` мусить очистити
користувача цілком незалежно від того, скільки в нього днів.

AC вимагав звіту про аркуші без відповідного користувача в БД, але
`GoogleSheetsService.get_workout_programs` вимагає `username`, щоб
побудувати назву аркуша — самостійно перелічити вкладки він не вміє.
Додано новий публічний метод `GoogleSheetsService.list_program_sheet_
usernames()` (парсить назви вкладок `"Програми (<username>)"` через
`spreadsheets().get(...)`, повертає список username) — використовується
лише для звіту (`sheet_usernames - db_usernames`), не для самого
імпорту.

`--dry-run` все одно робить реальний виклик `get_workout_programs` (щоб
порахувати, скільки рядків/днів буде імпортовано), просто не пише в БД —
це узгоджується з AC "показати, що буде імпортовано".

**SP:** 2

### ✅ GYM-30: WebApp — додавання днів і вправ у програму — **виконано**

**User story:** Як користувач (або тренер у режимі `?user=`), я хочу додати
вправу в день програми прямо в Mini App, щоб не ходити в бота.

**Acceptance criteria:**

- `POST /api/workout/program/exercise` (`{user?, day, muscle_group,
  exercise, sets_reps, comment?}`) → `add_exercises` + Sheets-дзеркало
  (GYM-28); валідація `sets_reps` тим самим правилом, що
  `process_sets_text` (`N/M`, `N|M` або «N» + reps) — винести парсер у
  `src/services/exercise_names.py`/`workout_program_parsing.py` і
  використати **в боті теж**, щоб формат був один. `muscle_group` — лише
  зі списку `MUSCLE_GROUPS`. Відповідь — доданий рядок у формі
  `GET /api/workout/program`.
- `/nutrition` → секція «Тренування»: кнопка «➕ Новий день» (день =
  `max(day)+1`, вибір групи м'язів чипами) і на картці дня — «➕ Вправа».
- `/workout` (list view): кнопка «➕ Додати вправу» внизу списку; bottom-sheet
  форма: назва (з автопідказкою з `GET /api/exercises?q=` — каталог
  GYM-27, щоб не плодити дублікати «Жим лежачи»/«жим лёжа»), швидкі чипи
  `3/10 3/12 4/8 4/10 4/12 5/5` (той самий набір, що
  `get_sets_reps_keyboard`), коментар. Після додавання вправа з'являється в
  списку без перезавантаження і одразу доступна для логування сетів
  (стан `exercises[]` у `workout.html`).
- Активна чернетка сесії (GYM-2c) не ламається: нова вправа додається в
  програму, а в чернетку потрапляє лише після першого залогованого сета.
- Тести: валідація `sets_reps`, `403` для чужого `user`, порядок
  `position`.

**Технічні підзадачі:**

- Backend: `api_add_program_exercise`, `GET /api/exercises`
  (`ExerciseRepository.search(q, limit=10)`).
- Frontend: `nutrition.html` (новий день/вправа), `workout.html`
  (bottom-sheet, стилі за зразком `showAddSetModal`).
- Bot: `process_sets_text`/`process_reps_text` використовують спільний
  парсер (поведінка не змінюється).

**Примітка щодо реалізації:** спільний парсер створено як новий файл
**`src/services/workout_program_parsing.py`** (не в `exercise_names.py` —
той про нормалізацію *назв*, це про формат *sets_reps*): `is_valid_sets_reps`
(валідація для API), `looks_like_combined_sets_reps`/`combine_sets_reps`
(та сама логіка, яку раніше містив тільки `process_sets_text`/
`process_comment`, тепер розділена на дві чисті функції й
використовується звідти ж — поведінка бота не змінилась, підтверджено
всім наявним `test_bot_handlers_workout_program.py`). `MUSCLE_GROUPS`
довелося **перенести** з `src/bot/keyboards.py` в цей самий файл: AC
хотів валідацію `muscle_group` проти єдиного списку і в боті, і в
webapp, а `src/webapp/server.py` імпортувати з `src.bot.keyboards`
небажано (напрямок залежності бот→webapp ніде в проєкті не
використовується, і навпаки теж не було). `src/bot/keyboards.py` тепер
робить `from src.services.workout_program_parsing import MUSCLE_GROUPS`
(з `# noqa: F401`, бо саме значення в файлі не використовується — лише
реекспортується), тож `keyboards.MUSCLE_GROUPS` (як і використовує
наявний `tests/test_bot_keyboards.py`) продовжує працювати без змін.

`process_reps_text` сам по собі парсер **не використовує** — з AC це
можна прочитати як вимогу, але в реальному коді комбінування `sets` +
`reps` в один рядок завжди відбувалося в `process_comment` (наступний
крок стану), не в `process_reps_text` (який лише зберігає `current_reps`
і переходить далі) — тому спільний парсер підключено саме туди;
`process_reps_text` не чіпали, бо там нічого дублювати.

`ExerciseRepository.search(q, limit=10)` — `contains`-пошук по
`normalized_name` (той самий `normalize_exercise_name`, що й
`get_or_create_by_name`), тож пошук нечутливий до регістру/пробілів/
апострофа так само, як дедуплікація каталогу. Порожній/пробільний `q`
повертає `[]` — це поле «почати вводити», не список усього каталогу.

`api_add_program_exercise` за зразком `api_delete_workout_day`
(GYM-28): резолвить власника через `_resolve_program_owner` (той самий
`403`/`404`), пише через `WorkoutProgramRepository.add_exercises`,
дзеркалить у Sheets лише якщо `owner.sync_workout_to_sheets` — і
некритично (падіння Sheets логується, запит все одно повертає `200`).
Валідація тіла: `day` — `int >= 1` (явна перевірка на `bool`, бо в
Python `bool` — підклас `int`, і без цього `day: true` пройшло б як
`day=1`), `muscle_group` — рядок зі списку `MUSCLE_GROUPS`, `exercise`
— непорожній рядок після `strip()`, `sets_reps` — `is_valid_sets_reps`.

Фронтенд (`workout.html`, `nutrition.html`): обидва додали bottom-sheet
модалку за зразком `showAddSetModal` — назва вправи з debounce-пошуком
(250мс, `AbortController` скасовує застарілий запит), чипи `sets_reps`
(`3/10 3/12 3/15 4/8 4/10 4/12 4/15 5/5 5/10` — повний набір
`get_sets_reps_keyboard`, а не скорочений приклад з AC, бо AC явно каже
«той самий набір, що `get_sets_reps_keyboard`»), коментар. У
`workout.html` модалка **не питає групу м'язів** — сторінка вже
скопована на один `day`+`muscle` (з `PARAM_MUSCLE`), і нова вправа
додається саме туди; у `nutrition.html` («➕ Новий день»/«➕ Вправа» на
картці дня) групу питає завжди чипами, бо один день може містити кілька
груп м'язів. Додана вправа в `workout.html` кладеться в `exercises[]` з
`_sets: []`/`_completed: false` і рендериться без перезавантаження —
`saveWorkoutSession()` пише лише в `localStorage` (офлайн-кеш), а
серверну чернетку сесії (`syncExerciseToServer`) чіпає лише логування
сета, тож AC "чернетка не ламається" виконується без додаткового коду.
У `nutrition.html` немає локального стану програми — після успішного
додавання просто викликається `loadWorkoutPrograms()` заново.

**Наявна (до цього тікета) особливість, не виправлена:**
`nutrition.html`'s day-card клік передає в `/workout` лише
`muscleGroups[0]` як `?muscle=` — якщо день містить вправи з кількох
груп м'язів, `/workout` показує тільки першу. Раніше це було
малоймовірним (день зазвичай = одна група), але GYM-30 робить
багатогрупові дні реальнішими (нова вправа в `nutrition.html` завжди
питає групу окремо). Виправлення (мультивибір груп при переході або
показ усіх груп дня на `/workout`) — поза скоупом цього тікета;
занотовано тут, щоб не загубилось.

Перевірено: весь набір тестів (юніт, `test_webapp_add_program_exercise.py`
та `test_workout_program_parsing.py`) зелений; наскрізна перевірка через
`aiohttp.TestClient` реальним HTTP-запитом
(`POST /api/workout/program/exercise` → `GET /api/exercises?q=` →
`GET /api/workout/program`, весь ланцюжок без моків); JS обох шаблонів
перевірено `esprima`-парсером (той самий прийом, що в GYM-22/25/26/37 —
без браузера в цьому середовищі, візуальний вигляд не перевірявся).

**SP:** 5

### ✅ GYM-31: Картка вправи — картинка, відео, опис — **виконано (з відхиленнями, див. примітку)**

**User story:** Як користувач, я хочу тапнути на назву вправи й побачити, як
її виконувати (картинка/відео/опис), якщо тренер це заповнив.

**Acceptance criteria:**

- `GET /api/workout/program` і `GET /api/workout/session/start` віддають
  для кожної вправи `exercise_id` і `has_details: bool` (є хоч одне з
  `description`/`image_url`/`video_url`), щоб UI не показував іконку «ⓘ»
  для порожніх карток.
- `GET /api/exercises/{id}` → `{id, name, muscle_group, description,
  image_url, video_url}` (`@webapp_auth`, без `?user=` — каталог спільний).
- `/workout`: іконка «ⓘ» біля назви (лише при `has_details`) → bottom-sheet:
  картинка (`<img loading="lazy">`, `max-width:100%`), опис, кнопка
  «▶️ Відео» через `tg.openLink(video_url)` (Instagram/YouTube/TikTok
  відкриваються в зовнішньому браузері/застосунку — всередині WebView
  вони часто блокують embed). `image_url` — будь-який https-URL; локальне
  хостингування картинок у `/static` не робимо в цьому плані.
- **Наповнення каталогу — поза скоупом** (див. «Відкриті питання»); у цьому
  таску контент з'являється лише через прямий запис у `exercises`
  (міграція/консоль). Тест: ендпоінт із заповненим і порожнім рядком.

**Технічні підзадачі:**

- Backend: `api_get_exercise`, розширення серіалізації програми.
- Frontend: `workout.html` — bottom-sheet деталей.

**Примітка щодо реалізації:** AC каже "**`GET`** `/api/workout/session/start`",
але в коді цей ендпоінт — **`POST`** (`app.router.add_post('/api/workout/
session/start', api_start_workout_session)`, було так і до GYM-31). Крім
того, його відповідь взагалі не містить переліку вправ — лише
`session_id`/`sets_by_exercise` (уже залоговані сети чернетки); список
вправ програми сторінка `workout.html` завжди бере окремим запитом
`GET /api/workout/program` (`loadProgram()` зливає обидві відповіді в
один `exercises[]`). Додавати `exercise_id`/`has_details` в `session/start`
не було куди — там немає структури "на кожну вправу", в яку це можна
покласти, і ніщо на фронтенді не читало б звідти ці поля. Тому це поле
розширено **лише** в `GET /api/workout/program` (`WorkoutProgramRepository
.get_program`, тепер `JOIN Exercise` замість самого `WorkoutProgramExercise`)
— саме звідти `workout.html` реально бере дані для рендеру.

Під час реалізації сам собі знайшов і виправив реальний баг: `POST
/api/workout/program/exercise` (GYM-30) формував відповідь вручну з
щойно створеного рядка й **не додав** нові поля `exercise_id`/
`has_details` — тобто вправа, додана через webapp-форму, не отримувала
"ⓘ" одразу (доти, доки сторінку не перезавантажать і `GET /api/workout
/program` не підхопить її заново). Виправлено — та ж форма відповіді,
що й `get_program`; `Exercise` для щойно доданого рядка підвантажується
явним `ExerciseRepository.get_by_id`, а не через ORM-зв'язок
`WorkoutProgramExercise.exercise` (lazy-load через relationship не
awaitable в async SQLAlchemy без явного eager-load — простіше й
безпечніше явним запитом).

`ExerciseRepository.get_by_id` — новий метод, тривіальний `select ...
WHERE id ==`. `api_get_exercise` (`GET /api/exercises/{id}`) без
перевірки власника — каталог спільний, той самий підхід, що й `GET
/api/exercises?q=` (GYM-30); `400` на нечисловий `id`, `404` — на
відсутній.

Фронтенд: іконка «ⓘ» додана і в list view (біля назви в списку вправ
дня), і в detail view (біля заголовка вправи) — AC каже "картка вправи"
в однині, але обидва місця показують назву вправи, і додавання іконки в
список коштувало один рядок розмітки плюс `stopPropagation()` (той
самий прийом, що вже використовує `deleteExercise`, щоб клік не
відкривав detail view). Bottom-sheet перевикористовує CSS `.modal-*`
класи, вже введені GYM-30 в цьому ж файлі; порожній `description`/
`image_url`/`video_url` (усі одразу) показує «Опис ще не додано» —
теоретично неможливо при коректному `has_details` (бекенд не покаже
іконку без жодного заповненого поля), але дає осмислений стан, якщо
дані розійшлися (наприклад, стара закешована `exercises[]` у
`localStorage`).

Перевірено: весь набір тестів (юніт, `test_webapp_get_exercise.py`)
зелений; наскрізна перевірка через `aiohttp.TestClient` реальним HTTP-
запитом (додавання вправи → заповнення `description`/`video_url` в БД →
`GET /api/workout/program` показує `has_details: true` → `GET
/api/exercises/{id}` повертає деталі); JS `workout.html` перевірено
`esprima`-парсером (без браузера в цьому середовищі, візуальний вигляд
не перевірявся).

**SP:** 3

### GYM-41: Групування по м'язах, безпечне видалення дня, підказка існуючих вправ

**User story:** Як користувач, я хочу бачити вправи дня згрупованими по
групі м'язів, не боятись випадково стерти вправи іншої групи при
видаленні, і не плодити дублікати каталогу, коли додаю вправу, що вже
є в списку.

**Контекст:** GYM-30 дозволив одному дню програми містити кілька груп
м'язів (кнопка «➕ Вправа»/«➕ Новий день» завжди питає групу окремо), але
відображення й видалення в `/workout` досі спроєктовані так, ніби день —
завжди одна група (спадок дизайну ще з Google Sheets). Це вже занотовано
як відкритий недолік у примітці до GYM-30 — цей тікет його закриває.

**Acceptance criteria:**

- `/workout`: якщо перейти на день без фільтра по групі (з картки дня в
  `/nutrition`, яка тепер веде на весь день, а не лише на
  `muscleGroups[0]`), список вправ показує **секції за групою м'язів**
  (заголовок-роздільник = емодзі + назва групи, вправи під ним — у
  порядку `position`, як і зараз), а не єдиний пласкій список.
  `GET /api/workout/program?day=N` (без `muscle`) — без змін у формі
  відповіді (пласкій список), групування — на клієнті, як і зараз
  робить `nutrition.html` для карток дня.
- `DELETE /api/workout/day` приймає необов'язковий `muscle`: якщо
  переданий — видаляє лише рядки цього дня **з цією групою м'язів**
  (нові рядки інших груп у тому самому дні лишаються); якщо відсутній —
  видаляє весь день (поточна поведінка, для кнопки «видалити весь
  день»). `WorkoutProgramRepository.delete_day` отримує необов'язковий
  параметр `muscle: str | None`, що додає умову у `WHERE`.
- `/workout`: кнопка видалення дня замінюється на дію на рівні секції
  (групи м'язів) — «Видалити [група]» під кожним заголовком секції,
  плюс окрема опція «Видалити весь день» (підтвердження з переліком
  усіх груп, що зникнуть). Мета — той самий клік не може випадково
  стерти групу, яку користувач не бачив на екрані.
- Форма «➕ Додати вправу»/«➕ Новий день» (`nutrition.html`,
  `workout.html`): поле назви вправи показує список уже доданих раніше
  вправ **одразу при фокусі** (до введення тексту), а не лише за
  запитом — `GET /api/exercises?q=` без `q` (або з порожнім `q`) починає
  повертати останні/найчастіші `limit` записів каталогу замість `[]`,
  щоб було з чого обрати, не друкуючи. Вибір зі списку — як і зараз,
  підставляє назву в поле; збережена поведінка пошуку при введенні
  тексту не змінюється.
- Тести: групування по м'язах (клієнтська логіка — юніт-тест чистої
  функції групування, винесеної з інлайну), `muscle`-scoped видалення
  дня (не займає інші групи), `GET /api/exercises` без `q` повертає
  непорожній список (за наявності записів у каталозі).

**Технічні підзадачі:**

- Backend: `WorkoutProgramRepository.delete_day(user_id, day,
  muscle=None)`; `ExerciseRepository.search` — порожній/відсутній `q`
  більше не рано повертає `[]`, а йде тим самим шляхом з `LIMIT`
  (сортування — за замовчуванням `ORDER BY name`, «найчастіші» — поза
  скоупом цього тікета, якщо не з'ясується дешево порахувати).
  `api_delete_workout_day` — читає й прокидає query-параметр `muscle`.
- Frontend: `workout.html` — групування списку на секції +
  секційне видалення; `nutrition.html` — day-card тепер веде на
  `/workout?day=N` без `muscle`; обидва — «список одразу при фокусі» в
  `showAddExerciseModal`.

**SP:** 3

---

## Epic 4 — Бот у групі: нагадування

### ✅ GYM-32: Реєстрація групи (`my_chat_member`) і модель `GroupChat` — **виконано**

**User story:** Як тренер, я хочу додати бота в групу клієнтів, щоб він
зареєструвався там і був готовий нагадувати.

**Acceptance criteria:**

- Таблиця `group_chats`: `id`, `chat_id` (BigInteger, unique, index),
  `title`, `is_active` (бот ще в групі), `added_by_telegram_id`,
  `remind_nutrition` (bool, default `True`), `nutrition_time` (`"HH:MM"`,
  default `"20:00"`), `remind_measurements` (bool, default `True`),
  `measurements_weekday` (0–6, default 0 = понеділок),
  `measurements_time` (default `"09:00"`), `remind_photos` (bool, default
  `False`), `photos_day_of_month` (1–28, default 1), `photos_time`
  (default `"09:00"`), `last_nutrition_sent_on` / `last_measurements_sent_on`
  / `last_photos_sent_on` (Date|null, локальна дата), `created_at`,
  `updated_at`. Час — у `settings.timezone` (одна зона на застосунок, як
  усюди).
- Хендлер `ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION)`
  на `my_chat_member` для `group`/`supergroup`: upsert `GroupChat`
  (`is_active=True`, `title`), привітання «Я нагадуватиму про харчування
  щодня о 20:00 і про заміри щопонеділка о 09:00. Налаштувати —
  `/reminders`». `LEAVE_TRANSITION` → `is_active=False` (рядок і
  налаштування лишаються — при поверненні бота відновлюються).
- Приватні чати цей хендлер ігнорує; `dp.resolve_used_update_types()`
  підхоплює `my_chat_member` автоматично (перевірити тестом, що тип є в
  списку).
- Тести: join/leave через `tests/bot_mocks.py` (додати `make_chat_member_updated`).

**Технічні підзадачі:**

- DB: модель + міграція; `GroupChatRepository` (`upsert_active`,
  `deactivate`, `get_active`, `update_settings`, `mark_sent`).
- Bot: `src/bot/handlers/group_reminders.py` (router у `setup_routers`).

**Примітка щодо реалізації:** `id` — звичайний автоінкрементний `Integer`
(як `Exercise`/`WorkoutProgramExercise` з GYM-27), не UUID як `User` —
AC явно перелічує поля й не каже про UUID, а `group_chats` ні з чим не
пов'язана через FK в інший бік (нічого не посилається на `GroupChat.id`
— усе шукає по `chat_id`), тож найновіша конвенція проєкту (прості
таблиці — простий PK) підійшла більше. `last_*_sent_on`/часові поля —
перший `Date`-стовпець у проєкті (досі всюди був або `DateTime`, або
рядки `"HH:MM"`) — довелося додати імпорт `Date`/`date` в
`src/database/models.py`.

`GroupChatRepository.upsert_active` на повторному приєднанні **не**
чіпає `added_by_telegram_id` (лишає того, хто додав бота вперше) і не
скидає жодного налаштування/`last_*_sent_on` — лише `is_active=True` й
оновлює `title` (сама назва групи могла змінитися, поки бота не було).
`update_settings` — явний список іменованих `| None`-параметрів (а не
`**kwargs`), щоб не приймати довільні поля моделі й лишатись
типобезпечним для mypy; `None` означає «не чіпати», не «очистити».
`mark_sent` мапить `reminder_type` ("nutrition"/"measurements"/"photos")
на відповідний стовпець через невеликий словник і кидає `ValueError` на
невідомий тип — жоден із них ще не викликається продакшн-кодом (GYM-33/
34 ще не реалізовані), але їх наявність і повне покриття тестами —
пряма вимога AC-технічних підзадач цього тікета.

Привітальне повідомлення шле через `event.answer(...)` (у
`ChatMemberUpdated` є той самий зручний метод, що й у `Message`/
`CallbackQuery` — `event.bot.send_message` не знадобився і мав
проблему: `event.bot` типізований як `Bot | None`, mypy справедливо
скаржився). Невдача відправки привітання (бот одразу заглушили в групі,
мережева помилка тощо) **не** відкочує реєстрацію в БД — той самий
принцип "запис у БД критичний, дзеркало/повідомлення — ні", що й у
Sheets-дзеркалі (GYM-2/28): `try/except` навколо лише `event.answer`,
`upsert_active` + `commit()` вже виконані до цього.

Тестування `my_chat_member` без реального `Update` виявилось
нетривіальним: `aiogram.types.Update` — pydantic-модель, що вимагає
рівно одне поле-подію заповненим через валідацію, незручно збирати з
мока. Замість повного `Dispatcher.feed_update()` тести гонять подію
через `group_reminders.router.my_chat_member.trigger(event)` —
той самий метод, який `feed_update()` викликає всередині, тож фільтри
(`ChatMemberUpdatedFilter` + `F.chat.type`) все ще реально
відпрацьовують, просто без обгортки в `Update`. Окремий тест
(`test_my_chat_member_is_a_used_update_type`) все ж будує справжній
`Dispatcher` — саме це й вимагає AC.

Під час написання тестів знайшов і виправив дрібний, але блокуючий
недолік наявного `tests/bot_mocks.py::make_chat`: воно робить
`MagicMock(spec=Chat)`, а `spec=` враховує лише атрибути, присутні в
`dir(Chat)` — а `title` (як і більшість pydantic-полів) там немає,
доступний лише на інстансі. Звернення до `chat.title` (яке додав цей
хендлер) падало з `AttributeError`, хоча раніше цей мок ніколи не
використовувався там, де `.title` читають. Виправлено додаванням
явного `title` параметра до `make_chat` (за замовчуванням `None`,
зворотно сумісно).

Перевірено: весь набір тестів (юніт, `test_group_chat_repository.py`,
`test_bot_handlers_group_reminders.py`, `test_migration_group_chats.py`)
зелений; міграція перевірена тим самим hand-wired-`Operations`-прийомом,
що й попередні (`create_table`/`drop_table` в обидва боки, унікальний
індекс на `chat_id` — тест на `IntegrityError` при дублі).

**SP:** 3

### ✅ GYM-33: `/reminders` — налаштування нагадувань у групі — **виконано**

**User story:** Як адмін групи, я хочу вмикати/вимикати типи нагадувань і
міняти час просто в чаті.

**Acceptance criteria:**

- `/reminders` у групі (лише `group`/`supergroup`; у приваті — підказка
  «Додайте мене в групу») показує inline-панель: три рядки-тогли
  `🍽 Харчування · щодня 20:00 [✅]`, `📏 Заміри · пн 09:00 [✅]`,
  `📸 Фото прогресу · 1-го числа 09:00 [❌]` і кнопки «⏰ Час…» для кожного
  (вибір з чипів `07:00 09:00 12:00 18:00 20:00 21:00`, для замірів — ще
  день тижня, для фото — число 1/15).
- Змінювати може лише учасник зі статусом `creator`/`administrator`
  (`bot.get_chat_member`), інші отримують `callback.answer("Лише адміни
  групи", show_alert=True)`; сам перегляд — усім.
- Callback-дані з префіксом `grem:` (щоб не перетинались з `program:`/
  `edit:`); панель редагується in-place (`edit_message_reply_markup`).
- Працює з увімкненим privacy mode (команди й callback-и доходять; читати
  повідомлення групи бот не потребує).
- Тести: не-адмін не змінює; toggle перемикає поле; час валідований.

**Примітка щодо реалізації:** знайшов і виправив реальний баг ще на
етапі написання тестів: перше формулювання callback-даних для часу було
`grem:settime:<type>:<HH:MM>` і парсилось як
`callback.data.split(":")[3]` — але `"HH:MM"` сам містить `:`, тож
`split(":")` розбиває `"20:00"` на `"20"` і `"00"` окремими елементами,
і `parts[3]` віддавав лише `"20"`, а не `"20:00"`. Тест
`test_valid_time_is_applied` це відразу впіймав (очікував `"07:00"`,
отримав `"20:00"` — час взагалі не змінювався). Виправлено: `time_str =
":".join(parts[3:])` замість `parts[3]` — той самий підхід, що вже
використовує `google_sheets.py` для склеювання шматків, розбитих зайвим
роздільником.

Клавіатури (`get_group_reminders_panel_keyboard`,
`get_group_reminders_time_keyboard`) додано в `src/bot/keyboards.py`
(поруч з рештою keyboard-білдерів проєкту), а не в `group_reminders.py`
— зберігає наявний поділ "клавіатури в keyboards.py, обробники в
handlers/*.py". Диспетчеризація toggle/`settime` за типом нагадування
зроблена явними `if/elif` по рядку `reminder_type`, а не через
`getattr`/`**{field: value}` в один рядок — перша версія з динамічним
`**kwargs`-розпакуванням не проходила mypy (`update_settings` приймає
конкретні іменовані `bool | str | int | None`-параметри, а не
`**kwargs`, тож mypy не міг статично звірити рядковий ключ з іменем
параметра).

`is_group_admin` — реальний виклик `bot.get_chat_member(chat_id,
user_id)`, перевірка `status in {ADMINISTRATOR, CREATOR}`
(`aiogram.enums.ChatMemberStatus`); мережева помилка/виняток при
виклику — трактується як "не адмін" (`except Exception: return False`),
щоб тимчасовий збій Telegram API не давав змогу змінювати налаштування
без перевірки. Malformed/несподіване `callback_data` (не з наших
кнопок) — `try/except (IndexError, KeyError, ValueError)` навколо
всього блоку розбору дій, відповідь `callback.answer()` без падіння
хендлера.

"Працює з privacy mode" — не окремий код, а властивість архітектури:
хендлери підписані лише на `Command("reminders")` і `callback_query`,
жодного generic `message`-хендлера, що читав би довільний текст групи,
тож привілей на читання повідомлень боту не потрібен за визначенням.

Тестування фільтрів (`Command("reminders")`, `F.data.startswith
("grem:")`) — той самий прийом, що в GYM-32
(`router.message.trigger(...)`/`router.callback_query.trigger(...)`
замість повного `Dispatcher.feed_update()`); `Command.__call__`
додатково вимагає `bot=` в `trigger(...)` (на відміну від
`ChatMemberUpdatedFilter`), з'ясовано методом проб через реальний
виклик. `tests/bot_mocks.py::_make_chat_member` перейменовано в публічний
`make_chat_member` — знадобився і для `my_chat_member` (`old_chat_member`/
`new_chat_member`, GYM-32), і тепер для `bot.get_chat_member(...)`
(GYM-33), тож переніс в один спільний хелпер замість дублювання;
`make_callback` отримав новий `bot=` параметр (за замовчуванням —
`MagicMock` з переднастроєним `get_chat_member = AsyncMock()`), той
самий патерн, що вже мав `make_message`.

Перевірено: весь набір тестів (юніт, `test_bot_handlers_reminders.py` —
33 тести) зелений; ручна наскрізна перевірка через
`router.message.trigger()`/`router.callback_query.trigger()` реальним
диспетчеризаційним шляхом (без моку самого хендлера).

**SP:** 5

### GYM-34: Планувальник і відправка нагадувань

**User story:** Як учасник групи, я хочу отримувати короткі нагадування з
кнопкою, що веде в потрібний розділ Mini App.

**Acceptance criteria:**

- Чиста функція `src/services/group_reminders.py: due_reminders(group,
  now_local: datetime) -> list[ReminderKind]`: тип «належить» відправці,
  якщо увімкнений, `now_local` ≥ налаштованого часу цього дня, день
  відповідає (щодня / weekday / day_of_month) і `last_*_sent_on <
  now_local.date()`. Тести: межа опівночі, вимкнений тип, уже надіслано
  сьогодні, бот перезапущений після 20:00 (надсилає з запізненням, але
  один раз), 29–31 число при `day_of_month=28`.
- Job `group_reminders` у `setup_scheduler` (`interval`, 5 хв): для всіх
  `is_active` груп → `due_reminders` → `send_message` → `mark_sent`.
  `TelegramForbiddenError`/`ChatNotFound` (бота вигнали без події) →
  `is_active=False`; інші помилки логуються, `last_*_sent_on` не
  оновлюється (повтор на наступному тику).
- Тексти (Markdown, той самий стиль, що `NotificationService`):
  - 🍽 «Час підбити харчування за сьогодні — залогуйте прийоми їжі та воду»
    +кнопка «🍎 Відкрити щоденник» → `https://t.me/<bot>?start=nutrition`;
  - 📏 «Понеділок — день замірів. Оновіть вагу в профілі» + «👤 Профіль» →
    `?start=profile`;
  - 📸 «Час для фото прогресу 📸 Зробіть фото в тих самих умовах, що й
    минулого разу» (без кнопки; бот фото не збирає — див. ризики).
- `/start <section>` у приватному чаті (`CommandStart(deep_link=True)`,
  `CommandObject.args ∈ {nutrition, profile, statistics}`) відповідає
  inline `web_app`-кнопкою на відповідну сторінку (у групі `web_app` не
  працює — тому дволанковий перехід). Невідомий аргумент → звичайний
  `/start`.
- Ім'я бота для deep-link — з `await bot.get_me()` один раз при старті
  (кешується в `set_bot_instance`-стилі), не з env.

**Технічні підзадачі:**

- Services: `group_reminders.py` (чиста логіка + `GroupReminderService`
  з відправкою).
- Bot: `bot.py: setup_scheduler` — новий job; `start.py` — deep-link.
- Tests: чиста логіка; сервіс з мокнутим `Bot`.

**SP:** 5

---

## Epic 5 — Бот: меню, кнопки, тексти

### ✅ GYM-35: Перейменувати chat-menu-кнопку «🍎 БЖУ» і пов'язані тексти — **виконано**

**User story:** Як користувач, я хочу, щоб кнопка меню називалась відповідно
до того, що відкриває (щоденник з харчуванням, тренуваннями, статистикою і
профілем), а не «БЖУ».

**Acceptance criteria:**

- Chat-menu-кнопка: `📱 Щоденник` → `/nutrition` (рекомендація; фінальну
  назву див. у «Відкритих питаннях»). Виставляється **глобально** при
  старті бота (`bot.set_chat_menu_button(menu_button=MenuButtonWebApp(…))`
  без `chat_id` — default для всіх приватних чатів), а per-chat виклик у
  `/start` прибирається (він більше не потрібен і лише перезаписував би
  default).
- Тексти в `user_profile.py`: «⚙️ Редагувати налаштування БЖУ» →
  «🎯 Цілі харчування», «🍎 Відкрити трекер БЖУ» → `web_app`-кнопка
  «📱 Відкрити щоденник» (inline `web_app` у приваті працює — замість
  alert'а «Натисніть кнопку 🍎 БЖУ в меню бота»); заголовок
  `_format_nutrition_settings` → «🎯 Цілі харчування».
- `/nutrition` (`handlers/nutrition.py`): текст «📊 Трекер харчування» →
  «🍎 Харчування», опис актуалізовано (сьогодні, статистика, фото).
- Тести: `test_bot_handlers_start.py` — `set_chat_menu_button` не
  викликається в `/start`; startup-хук викликає з очікуваним текстом.

**Примітка щодо реалізації:** глобальна кнопка меню — новий
`configure_default_menu_button(bot)` у `src/bot/bot.py`, викликається раз
у `run_bot()` одразу після `create_bot()`; сама функція — no-op без
`WEBAPP_URL` (`tests/test_bot_startup.py`). Опис `/nutrition` **не**
згадує фото → БЖВ — цей функціонал ще не реалізований (GYM-23/24), казати
про нього в тексті бота зараз означало б обіцяти неіснуючу фічу; коли
GYM-24 буде готовий, рядок можна дописати. `get_profile_settings_keyboard`
(`user_profile.py`) тепер сам вирішує тип другої кнопки: `web_app` при
заданому `WEBAPP_URL`, інакше — стара callback-кнопка з тим самим текстом
(`open_webapp_callback` лишається лише як фолбек на цей випадок —
`tests/test_bot_handlers_user_profile.py`).

**Доповнення (пост-реліз):** текст кнопки спрощено з `📱 Щоденник` до
лише `📱` за проханням користувача — див. «Відкриті питання» вище.

**SP:** 1

### ✅ GYM-36: Клавіатури головного/адмінського меню, `/start`, `/help`, `set_my_commands` — **виконано (з відхиленнями, див. примітку)**

**User story:** Як користувач, я хочу з головного меню одразу потрапляти в
харчування, тренування, статистику і профіль, а `/help` має описувати те,
що бот справді вміє.

**Acceptance criteria:**

- `get_main_menu_keyboard` (при заданому `WEBAPP_URL`; без нього — як
  зараз, лише текстові кнопки):

  ```plaintext
  [🍎 Харчування (web_app /nutrition)] [🏋️ Тренування (web_app /nutrition?tab=workout)]
  [📊 Статистика (web_app /statistics)] [👤 Профіль]
  [📅 Розклад] [📝 Мої записи]
  [ℹ️ Допомога]
  ```

  `nutrition.html` читає `?tab=workout` і одразу відкриває секцію
  «Тренування» (`showWorkoutSection`).
- `get_admin_menu_keyboard`: ті самі рядки + зверху
  `[💪 Програма тренувань] [📋 Переглянути програми]` і
  `[➕ Додати тренування] [📈 Адмін-статистика]`. Текст адмінської
  статистики (`admin.py:280`) перейменовується з `📊 Статистика` на
  `📈 Адмін-статистика` — інакше після появи `📊 Статистика`-web_app у
  головному меню два різні елементи мають однаковий підпис.
- `/start`: реєстрація як зараз; текст описує розділи щоденника
  (харчування, фото → БЖВ, тренування, статистика, профіль) і запис на
  заняття; підтримує deep-link (GYM-34).
- `/help`: актуальний список команд і розділів (без «📅 Розклад» як
  єдиного сценарію); згадка про групові нагадування і `/reminders`.
- `set_my_commands` при старті: `start`, `help`, `nutrition`, `statistics`,
  `schedule`, `my` для `BotCommandScopeAllPrivateChats`; `reminders` для
  `BotCommandScopeAllGroupChats`; `admin` для `BotCommandScopeChat`
  кожного `admin_user_ids`.
- Тести: `test_bot_keyboards.py` — склад кнопок з/без `WEBAPP_URL`;
  `/help` містить `/nutrition`, `/statistics`, `/reminders`.

**Технічні підзадачі:**

- Bot: `keyboards.py`, `start.py`, `admin.py` (текст кнопки),
  `bot.py: run_bot` — `set_my_commands` + default menu button (GYM-35)
  в одному startup-хелпері `configure_bot_commands(bot)`.
- Frontend: `nutrition.html` — `?tab=workout`.
- README «Команди бота».

**Примітка щодо реалізації:** три пункти AC явно посилаються на Epic 4
(GYM-32…34), який іде пізніше в спринт-плані (Sprint 6) і на момент цього
таска не реалізований — виконано без них, свідомо:

- **Без «фото → БЖВ» у тексті `/start`** — фіча ще не збудована (GYM-23/24);
  обіцяти її в тексті бота зараз означало б казати неправду (те саме
  рішення, що й у GYM-35 для `/nutrition`).
- **Без підтримки deep-link (`/start <section>`)** — це прив'язано до
  групових нагадувань (GYM-34), самих нагадувань ще немає, тож посилання
  нікуди вести не буде; додається разом із GYM-34.
- **Без `reminders` у `BotCommandScopeAllGroupChats`** і без згадки
  `/reminders` у `/help` — команда без хендлера (GYM-33 ще не зроблений)
  показувалась би в списку команд Telegram, але нічого не відповідала б.
  Реєстрація команд для приватних чатів і per-admin `/admin`
  (`BotCommandScopeChat`) — зроблена повністю; групові команди додасть
  GYM-33 у той самий `configure_bot_commands`.

Решта AC — без змін: `get_main_menu_keyboard`/`get_admin_menu_keyboard` у
`src/bot/keyboards.py` (адмінське меню тепер будується як
admin-рядки + `list(get_main_menu_keyboard().keyboard)`, щоб не дублювати
логіку show/hide WebApp-кнопок), перейменування `📊 Статистика` →
`📈 Адмін-статистика` в `admin.py`, `?tab=workout` у `nutrition.html`
(читається одразу при завантаженні, викликає вже наявний
`showWorkoutSection()`), `configure_bot_commands(bot)` в `src/bot/bot.py`
замінив і поглинув `configure_default_menu_button` з GYM-35 (виклик у
`run_bot()` — один, одразу після `create_bot()`). Тести:
`tests/test_bot_keyboards.py`, `tests/test_bot_startup.py`.

**SP:** 3

---

## Наскрізні задачі

- ✅ **GYM-37 — Уніфікація нижньої навігації Mini App — виконано.** Прибрано
  мертвий пункт `⚙️ Налаштування` (`href="#"`) з `nutrition.html`,
  `profile.html`, `statistics.html`; на всіх трьох — однаковий набір
  `Сьогодні · Тренування · Статистика · Профіль` (`Тренування` →
  `/nutrition?tab=workout`, GYM-36) — `profile.html`/`statistics.html`
  раніше взагалі не мали пункту «Тренування», не лише «Налаштування» було
  мертвим. `.nav-item.active` більше ніде не хардкодиться в розмітці —
  однакова функція `highlightActiveNavItem()` (буквально та сама, скопійована
  в усі три файли — «спільний фрагмент» тут означає «синхронізовано
  копіпастом», бо в цих server-rendered шаблонах немає механізму спільного
  JS-модуля) виставляє `active` за `location.pathname`+`search` при
  завантаженні сторінки. Точний збіг query достатньо вимагати лише для
  хрефів з pathname, який ділять кілька пунктів (`/nutrition` і
  `/nutrition?tab=workout` — два різні пункти на одній сторінці); інші
  пункти збігаються по pathname без урахування чужого query, інакше
  `/statistics?tab=history` (GYM-40) чи `/workout?user=…` не підсвітили б
  свій пункт. На `nutrition.html` власний in-page перемикач
  Сьогодні/Тренування (без зміни URL) як і раніше сам виставляє `active` на
  клік — генералізувати це на інші сторінки нема сенсу (у них немає
  еквівалента). Дорогою прибрано мертві гілки `href === '#'` з
  обробників кліків усіх трьох сторінок (`tg.showAlert('Розділ буде
  доступний незабаром!')` — після видалення єдиного `#`-пункту цей код
  ніколи не спрацював би). **SP: 1**
- **GYM-38 — Інтеграційні тести нових ендпоінтів.** За зразком
  `tests/test_webapp_statistics_integration.py` (реальний `TestClient`):
  auth на кожному новому `/api/*`, `403` за чужий `user` для не-адміна,
  multipart на `/api/nutrition/meal/photo` (мок OpenAI), наскрізний
  сценарій «додати вправу через `POST /api/workout/program/exercise` →
  побачити в `GET /api/workout/program` → залогувати сет → побачити в
  `/api/statistics/exercises`». **SP: 3**
- **GYM-39 — Документація.** README: «Функціонал» (фото → БЖВ, програми в
  БД, групові нагадування), «Команди бота», «База даних» (`exercises`,
  `workout_program_exercises`, `group_chats`, нові поля `daily_nutrition`/
  `profiles`), «Google Sheets структура» (тепер — лише опційне дзеркало;
  крок імпорту GYM-29), розділ «OpenAI» (`OPENAI_API_KEY`, `OPENAI_MODEL`,
  орієнтовна вартість, що фото не зберігаються); `.env.example`. **SP: 1**

---

## MVP (≈ 32 SP)

Мінімальний набір, що дає: коректне «Сьогодні» з назвами страв і
вимкненням води, програми в БД з додаванням вправ із WebApp, і актуальне
меню бота:

| Таск | SP |
| ---- | -- |
| GYM-35 chat-menu-кнопка | 1 |
| GYM-36 клавіатури, `/start`, `/help`, команди | 3 |
| GYM-21 тип запису / назва / локальна доба | 3 |
| GYM-22 UI «Сьогодні» | 5 |
| GYM-25 вимкнення води | 3 |
| GYM-27 моделі програм і вправ | 3 |
| GYM-28 програми в БД, Sheets — дзеркало | 8 |
| GYM-29 імпорт із Sheets | 2 |
| GYM-30 додавання вправ у WebApp | 5 |
| GYM-39 документація | 1 |

Фото → БЖВ (GYM-23/24), картка вправи (GYM-31), групування/безпечне
видалення по м'язах (GYM-41), профіль (GYM-26), картка тренування
сьогодні (GYM-40) і групові нагадування (Epic 4) додаються інкрементально,
кожен — самодостатній реліз.

## Рекомендована послідовність (sprint order)

1. **Sprint 1:** GYM-35, GYM-36, GYM-21, GYM-25 — швидкі помітні зміни в
   боті + фундамент харчування
2. **Sprint 2:** GYM-22, GYM-40, GYM-26, GYM-37 — UI «Сьогодні» (+ картка
   тренування) і «Профіль»
3. **Sprint 3:** GYM-27, GYM-28, GYM-29 — програми в БД (+ імпорт одразу
   після деплою)
4. **Sprint 4:** GYM-30, GYM-31, GYM-41 — додавання вправ, картка вправи,
   групування/безпечне видалення по м'язах
5. **Sprint 5:** GYM-23, GYM-24 — фото → БЖВ
6. **Sprint 6:** GYM-32, GYM-33, GYM-34 — групові нагадування
7. **Sprint 7:** GYM-38, GYM-39 — інтеграційні тести + документація

## Відкриті питання та ризики

### Перенесено з фази 1 (WEBAPP_STATISTICS_PLAN.md)

- **`is_admin()` заглушений** (`workout_program.py:58`) — будь-який
  користувач може відкрити програму/лог будь-якого username. У фазі 1 це
  успадкувала статистика (`?user=<username>` на `/statistics` покаже чужі
  дані). **Статус у фазі 2:** закривається в GYM-28 (спільний
  `_resolve_program_owner` з перевіркою `admin_user_ids`, застосований до
  `/api/workout/*` і `/api/statistics/*`; `is_admin` у боті — реальна
  перевірка). До GYM-28 дірка лишається, і GYM-30 (додавання вправ із
  WebApp) **не можна** випускати раніше за GYM-28.
- **Username як ключ Sheets.** Зміна Telegram-username розриває зв'язок з
  аркушами `Логи (<old>)`/`Програми (<old>)`. **Статус:** після GYM-28
  Sheets — лише опційне дзеркало, тому розрив зачіпає тільки його (дані в
  БД цілі). Імпорт GYM-29 матчить аркуші за **поточним** username —
  аркуші користувачів, які вже змінили username, лишаться неімпортованими
  (звіт скрипта їх перелічить; ручний `--user` не допоможе, бо аркуш
  названий старим ім'ям — потрібен окремий параметр `--sheet-name`, якщо
  таке трапиться).
- **Sheets як джерело істини для програм.** **Статус:** вирішується цим
  планом (Epic 3). Після нього Sheets ніде не є джерелом істини;
  «повний відхід від Sheets» (видалення інтеграції) — не потрібен, дзеркало
  лишається як опція для тих, кому зручні таблиці.
- **Одиниця серії — тиждень** (реалістично для 3–4 тренувань/тиждень).
  Якщо потрібна денна серія — змінюється лише `calculate_streak`. Без змін.
- **Історія до GYM-2 відсутня в статистиці** (GYM-2b скасовано). Серія/PR/
  об'єм стартують «з нуля» з моменту розгортання GYM-2. Без змін; GYM-29
  імпортує **програми**, а не логи, і не змінює цього рішення.

### Нові в фазі 2

- **Точність фото → БЖВ.** Оцінка порції з фото має похибку ±30–50 %;
  саме тому результат — чернетка з бейджем впевненості, а не запис. Ризик:
  користувачі довірятимуть цифрам більше, ніж варто. Мінімум — підказка
  «Перевірте порцію» в `/meal-entry` (GYM-24). Вибір моделі
  (`gpt-4o-mini` за замовчуванням) — компроміс ціна/якість; перевірити на
  10–20 реальних фото перед релізом і за потреби підняти до `gpt-4o` через
  `OPENAI_MODEL`.
- **Вартість і ліміти OpenAI.** Орієнтовно $0.002–0.01 за фото при
  1024 px; без per-user rate-limit один користувач може «спалити» бюджет.
  У GYM-23 ліміту немає свідомо (MVP, малий закритий круг користувачів);
  якщо бот піде у ширшу групу — додати `daily_photo_limit` у профіль/конфіг
  окремим таском. Ключ — лише в env сервера, у WebApp не потрапляє.
- **Приватність фото.** Фото їжі проксюється в OpenAI і не зберігається в
  нас; але OpenAI може зберігати вхідні дані за своєю політикою
  (за замовчуванням API-дані не використовуються для тренування, але
  зберігаються до 30 днів для abuse-моніторингу). Згадати в `/help` і
  README. Якщо це неприйнятно — фіча вимикається порожнім ключем.
- **`input[type=file]` у Telegram WebView.** На iOS/Android Telegram
  зазвичай відкриває системний вибір камери/галереї, але траплялися
  регресії в окремих версіях клієнта. Перевірити в GYM-24 на трьох
  платформах; **фолбек** — приймати фото в приватному чаті бота
  (`F.photo`-хендлер → той самий `recognize_food` → відповідь з оцінкою і
  inline-кнопкою «Зберегти як прийом їжі»). Фолбек не в скоупі, але це
  ~3 SP поверх GYM-23, якщо знадобиться.
- **Назва chat-menu-кнопки — вирішено.** Спершу GYM-35 поставив `📱
  Щоденник`, але користувач і далі бачив старий підпис «🍎 БЖУ» в
  реальному боті (причина не з'ясована в цій сесії — не встановлено, чи
  це запущений процес зі старим кодом, чи клієнтський кеш Telegram; сам
  код на момент запиту вже містив правильний рядок). За проханням
  користувача текст спрощено до лише **`📱`** (без слова) — рядок у
  `configure_bot_commands` (`src/bot/bot.py`), змінити дешево, якщо
  знадобиться ще раз. Якщо після цієї зміни кнопка все ще показує старий
  текст — перезапустіть бота; якщо і це не допоможе, перевірте кеш
  клієнта Telegram (вийти з чату з ботом і зайти знов).
- **Кнопки `📅 Розклад`/`📝 Мої записи` в головному меню — вирішено:
  залишені.** GYM-36 додав їх у `get_main_menu_keyboard`
  (`src/bot/keyboards.py`) як окремий рядок, що завжди показується
  (незалежно від `WEBAPP_URL` — це прості текстові кнопки, не `web_app`).
  Рішення за замовчуванням: хендлери й тести на них уже існували й
  працювали, приховані лише через відсутність кнопки в клавіатурі — це
  виглядало як недогляд, а не свідоме рішення «не використовуємо групові
  заняття». Якщо на практиці виявиться, що запис на заняття
  дійсно не потрібен — прибрати рядок з клавіатури тривіально (хендлери й
  команди `/schedule`/`/my` лишаються незалежно).
- **Наповнення каталогу вправ (GYM-31).** Схема є, контент — ні. Варіанти
  для наступного плану: (а) адмінський FSM у боті «✏️ Вправа → надіслати
  фото/лінк/опис» (фото → `file_id` Telegram + віддача через
  `/api/exercises/{id}/image` проксі, щоб не хостити файли); (б) CSV/Sheets
  імпорт каталогу; (в) ручне заповнення в БД. Поки що `image_url` — лише
  зовнішній https-URL. Рішення не блокує цей план.
- **Дублікати назв вправ.** До GYM-27 назви — вільний текст із бота і
  Sheets, тож у `workout_sets.exercise_name` уже є варіанти написання однієї
  вправи (статистика GYM-5a/8 їх бачить як різні). `normalize_exercise_name`
  об'єднає **нові** записи; злиття історичних варіантів у `workout_sets` —
  окремий таск (ручний маппінг «варіант → канон»), не робимо тут.
- **Заміри — лише нагадування, без історії.** У БД є лише `Profile.weight`
  (поточне значення); нагадування «оновіть вагу» перезапише його без
  історії. Таблиця `body_measurements` (вага, талія, фото) і графік ваги в
  статистиці — логічний наступний епік, але поза цим планом.
- **Фото прогресу — бот їх не збирає.** Нагадування 📸 лише просить зробити
  фото; зберігання (у групі, в приваті, в БД як `file_id`) не проєктується,
  бо пов'язано з приватністю і з `body_measurements` вище.
- **Групи: privacy mode і права.** `/reminders` і callback-и працюють при
  увімкненому privacy mode; перевірка «адмін групи» — через
  `get_chat_member` на кожен callback (один запит; кешувати не варто —
  права міняються). Якщо бота зроблять адміном групи, нічого не зміниться.
  У супергрупах із темами (forum) повідомлення підуть у General —
  `message_thread_id` не підтримуємо в цьому плані.
- **Одна таймзона на застосунок** (`settings.timezone`). Групи в іншій зоні
  отримуватимуть нагадування «о 20:00 за Києвом». Поле `timezone` у
  `group_chats` не додаємо, доки не з'явиться реальна потреба.
- **Кількість міграцій.** У плані 5 міграцій (GYM-21, 25, 27, 32 + за
  потреби). Тримаємо по одній на таск (як у фазі 1), не об'єднуємо, щоб
  PR-и лишались незалежними; `alembic upgrade head` під час старту
  (`bot.py:91`) застосує їх послідовно.
- **Порядок релізу GYM-28 → GYM-29.** Між деплоєм GYM-28 і запуском імпорту
  WebApp показуватиме порожні програми. Вікно коротке (хвилини), але
  користувачів попередити; альтернатива — запускати імпорт автоматично при
  старті, якщо таблиця порожня і `GOOGLE_SPREADSHEET_ID` заданий. Обрано
  ручний запуск (прозоріше, `--dry-run` спершу).
