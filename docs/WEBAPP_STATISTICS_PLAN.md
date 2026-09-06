# План реалізації: статистика та пов'язані WebApp-функції

> Формат: Epic → Story-таски (Jira-стиль). Кожен таск має user story, acceptance
> criteria, технічні підзадачі (DB / Backend / Frontend / Bot) та оцінку в
> стори-поінтах (SP, Fibonacci: 1‑2‑3‑5‑8‑13).

## Контекст

Наразі в проєкті є Telegram Mini Apps (`src/webapp/templates/*.html`,
`src/webapp/server.py`), відкриті через `WebAppInfo`:

- `/nutrition`, `/meal-entry`, `/profile` — харчування та профіль (дані в БД:
  `daily_nutrition`, `profiles`)
- `/workout` — тренування (лог **зберігається лише в Google Sheets**, аркуш
  `Логи (<user>)`, через `GoogleSheetsService.save_workout_log` /
  `get_last_workout_log`, `src/services/google_sheets.py:1287`)

Статистики тренувань (прогрес, PR, стріки) немає взагалі. Адмінська
`📊 Статистика` (`src/bot/handlers/admin.py:280`) показує лише кількість
користувачів/бронювань і не стосується тренувань чи харчування.

### Важливі особливості поточного коду, що впливають на план

- **Власник тренування ≠ той, хто відкрив WebApp.** Програми та логи
  прив'язані до `user` = `User.username` (`_get_workout_users`,
  `src/bot/handlers/workout_program.py:34`), а `is_admin()` заглушений і
  завжди повертає `True` (`:58`). Тренер може відкрити
  `/workout?user=<client>` і залогувати тренування за клієнта. Тому
  `user_id` у БД треба резолвити з параметра `user` (username), а
  `telegram_id` з `initData` використовувати **лише для авторизації**.
- **Username — нестабільний ключ.** Користувач може змінити Telegram-username,
  і аркуш `Логи (<old>)` відірветься від нього; користувачі без username
  взагалі не можуть мати програму. Зберігання `user_id` (GUID) у БД це лікує.
- **Таймзони.** `api_save_workout_log` пише `datetime.now()` (локальний час
  сервера), нутриція — `utcnow()`, є `settings.timezone`. Усі агрегації «за
  день/тиждень» мають групувати в `settings.timezone`, а зберігати — UTC.
- **Дублювання auth-коду.** Кожен `/api/*` копіює ~8 рядків валідації
  `initData`. Новим ендпоінтам (їх буде ~10) потрібен спільний декоратор.

### Ключове архітектурне рішення (Epic 0)

Агрегації (сума об'єму за тиждень, пошук PR, стріки) на Google Sheets API
повільні, лімітовані квотами і не підтримують SQL-агрегацію. Тому весь план
будується на перенесенні логів тренувань у БД з **дублюючим записом у Sheets**
(щоб не ламати існуючий перегляд/експорт) та **одноразовим бекфілом** історії з
аркушів `Логи (*)`. Аркуші `Програми (<user>)` не чіпаємо — Sheets лишається
джерелом істини для програм.

## Definition of Done (для кожного таска)

- Розрахункова логіка (PR, стрік, агрегації) — чисті функції в
  `src/services/statistics.py` з unit-тестами в `tests/` **у тому ж PR**.
- Нові `/api/*` ендпоінти використовують спільний auth-декоратор (GYM-0).
- Дати зберігаються в UTC; групування по днях/тижнях — у `settings.timezone`.
- Покриття CI не падає нижче порогу (60%).
- Текст UI/повідомлень — українською, у стилі існуючих екранів.

## Огляд епіків

| Epic | Назва | SP | Пріоритет |
| ---- | ----- | -- | --------- |
| 0 | Фундамент: auth-декоратор, лог тренувань у БД, бекфіл | 15 | Must (блокує все інше) |
| 1 | Статистика тренувань (WebApp) | 21 | Must |
| 2 | Особисті рекорди (PR) | 13 | Should |
| 3 | Історія / календар тренувань | 8 | Should |
| 4 | Стрік і досягнення | 11 | Could |
| 5 | Статистика харчування | 13 | Should |
| — | Наскрізні задачі | 8 | — |

Загалом: **≈ 89 SP**. MVP (див. нижче): **≈ 33 SP**.

---

## Epic 0 — Фундамент

### GYM-0: Спільний auth-декоратор для `/api/*`

**User story:** Як розробник, я хочу один декоратор для перевірки `initData`,
щоб нові ендпоінти не дублювали код валідації.

**Acceptance criteria:**

- Декоратор `@webapp_auth` (або middleware) у `src/webapp/auth.py`: валідує
  `Authorization` через `validate_telegram_webapp_data`, при помилці повертає
  `401`, інакше прокидає `telegram_user: dict` у handler.
- Існуючі ендпоінти **не** переписуються масово (лише за бажанням) — мета
  зняти дублювання для нових.
- Unit-тест: валідний/невалідний/порожній `initData`.

**SP:** 2

### GYM-1: Моделі `WorkoutSession` + `WorkoutSet` та міграція

**User story:** Як розробник, я хочу зберігати тренування (сесію) і кожен
підхід у БД, щоб швидко агрегувати статистику без Google Sheets API.

**Acceptance criteria:**

- Таблиця `workout_sessions`: `id`, `user_id` (FK → `users.id`, GUID, index),
  `day` (int|null), `muscle_group` (String|null), `duration_seconds` (int),
  `performed_at` (DateTime UTC, index), `created_at`.
- Таблиця `workout_sets`: `id`, `session_id` (FK → `workout_sessions.id`,
  index), `user_id` (FK → `users.id`, денормалізовано для швидких вибірок),
  `exercise_name`, `muscle_group`, `set_number`, `weight` (Float),
  `reps` (Integer), `planned_sets_reps` (String|null), `performed_at`
  (DateTime UTC, дубль з сесії для індексу).
- Індекси: `workout_sets(user_id, exercise_name, performed_at)`,
  `workout_sessions(user_id, performed_at)`.
- Alembic-міграція `alembic revision --autogenerate -m "add workout sessions and sets"`.
- Сесія — одиниця для історії, стріку та тривалості; два тренування в один
  день не змішуються.

**Технічні підзадачі:**

- DB: класи `WorkoutSession`, `WorkoutSet` у `src/database/models.py` (за
  зразком `DailyNutrition`), relationships `User.workout_sessions`,
  `WorkoutSession.sets`.
- DB: міграція в `alembic/versions/`, перевірити на SQLite і PostgreSQL.
- Backend: `WorkoutSessionRepository` / `WorkoutSetRepository` у
  `src/database/repository.py` — `create_session_with_sets(...)`,
  `get_sets_by_user_and_exercise(...)`, `get_sessions_by_period(...)`.
- Backend: `UserRepository.get_by_username(username) -> User | None`.

**SP:** 3

### GYM-2: Запис у БД паралельно з Google Sheets

**User story:** Як користувач, я хочу, щоб мій лог тренування зберігався
надійно, а історія в Sheets залишалась доступною як і раніше.

**Acceptance criteria:**

- `api_save_workout_log` (`src/webapp/server.py`) резолвить власника з
  `body["user"]` через `UserRepository.get_by_username`; якщо користувача не
  знайдено — `404 {"error": "User not found"}` **до** запису в Sheets.
  `telegram_id` з `initData` використовується лише для авторизації.
- Після успішного запису в Sheets створюється `WorkoutSession` з усіма
  `WorkoutSet` однією транзакцією; `performed_at` = UTC-час завершення
  (`utcnow()`), `duration_seconds` з тіла запиту.
- Якщо запис у БД падає — лог у Sheets усе одно збережений, помилка лише
  логується (як у `_sync_workout_to_calendar`).
- Тести: правильна кількість `workout_sets`, правильний `user_id` (власник, а
  не той, хто відкрив), 404 для невідомого username.

**Технічні підзадачі:**

- Backend: розширити `api_save_workout_log`.
- Tests: тест подвійного запису (мок Sheets + тестова БД).

**SP:** 5

### GYM-2b: Бекфіл історичних логів із Google Sheets

**User story:** Як користувач, я хочу бачити статистику по всіх минулих
тренуваннях, а не лише по тих, що зроблені після оновлення.

**Acceptance criteria:**

- Скрипт `scripts/import_workout_logs.py`: читає всі аркуші `Логи (<user>)`
  (формат дати `DD.MM.YYYY`, 9 колонок: date, exercise, muscle_group, day,
  set_number, weight, reps, planned_sets_reps, timestamp), мапить `<user>` →
  `User.username`, створює сесії (групування по `date + day`, бо в Sheets
  немає id сесії) і сети.
- Ідемпотентний: повторний запуск не створює дублікатів (перевірка по
  `user_id + performed_at + exercise_name + set_number`).
- `timestamp` з Sheets інтерпретується в `settings.timezone` і конвертується в
  UTC; для рядків без timestamp — `date` 12:00 локального часу.
- Рядки з порожньою вагою/повтореннями пропускаються (як у
  `get_last_workout_log`); аркуші користувачів, яких немає в БД, — логуються
  і пропускаються, скрипт не падає.
- Dry-run режим (`--dry-run`) виводить, що буде імпортовано.

**SP:** 5

---

## Epic 1 — Статистика тренувань (WebApp)

### GYM-3: Сторінка `/statistics` у Mini App

**User story:** Як користувач, я хочу відкрити окрему сторінку статистики з
головного меню бота, щоб бачити свій прогрес по тренуваннях.

**Acceptance criteria:**

- Handler `statistics_handler` віддає `statistics.html`, маршрут
  `GET /statistics`.
- Сторінка має вкладки: «Об'єм», «Прогрес по вправі», «Активність»; далі
  додаються «Рекорди», «Історія», «Досягнення» (Epic 2–4).
- Стилі відповідають існуючим (`workout.html`, `profile.html`), підтримка
  `Telegram.WebApp.themeParams`.
- Сторінка показує статистику того користувача, чий `telegram_id` в
  `initData` (для тренера — опційний query-параметр `?user=<username>`, як у
  `/workout`).

**Технічні підзадачі:**

- Frontend: `src/webapp/templates/statistics.html` (vanilla JS, за зразком
  `workout.html`), підключення Chart.js (GYM-17).
- Backend: `statistics_handler` + реєстрація в `create_webapp()`.

**SP:** 5

### GYM-4: API — об'єм тренувань за період і по м'язових групах

**User story:** Як користувач, я хочу бачити скільки тоннажу (вага × повтори)
я підняв за тиждень/місяць в розрізі груп м'язів, щоб оцінити баланс
навантаження.

**Acceptance criteria:**

- `GET /api/statistics/volume?period=week|month|all&muscle=<optional>`.
- Відповідь: `{"by_day": [{date, volume}], "by_muscle": [{muscle_group,
  volume, sets_count}], "total_volume"}`; з фільтром `muscle` `by_muscle`
  містить один елемент, `by_day` — лише цю групу.
- Межі періоду і групування по днях — у `settings.timezone`.
- Порожні періоди повертають нулі/порожні масиви, а не помилку.

**Технічні підзадачі:**

- Backend: `api_get_volume_statistics`, SQL-агрегація (`func.sum(weight*reps)`,
  `group_by`) через `WorkoutSetRepository`.
- Frontend: стовпчиковий графік по днях + donut/bar по групах.

**SP:** 5

### GYM-5a: API — прогрес по конкретній вправі

**User story:** Як користувач, я хочу отримати дані зміни робочої ваги і
повторень по вправі у часі.

**Acceptance criteria:**

- `GET /api/statistics/exercises` — унікальні `exercise_name` користувача з
  `muscle_group`.
- `GET /api/statistics/exercise-progress?exercise=<name>` — список
  `{date, max_weight, total_reps, total_volume, top_set: {weight, reps}}`
  по сесіях, відсортовано за датою.

**SP:** 3

### GYM-5b: UI — прогрес по конкретній вправі

**User story:** Як користувач, я хочу обрати вправу і побачити графік зміни
ваги/повторень, щоб бачити прогрес.

**Acceptance criteria:**

- Dropdown вибору вправи (групування по м'язових групах).
- Два лінійні графіки: макс. вага і повторення; порожній стан «Ще немає
  даних по цій вправі».

**SP:** 5

### GYM-6: API — загальна активність

**User story:** Як користувач, я хочу бачити скільки тренувань я зробив за
період і середню тривалість, щоб відстежувати регулярність.

**Acceptance criteria:**

- `GET /api/statistics/summary?period=week|month|all` →
  `{workouts_count, avg_duration_minutes, total_volume, most_trained_muscle}`.
- Рахується по `workout_sessions` (одна сесія = одне тренування).

**Технічні підзадачі:**

- Backend: `api_get_statistics_summary`.
- Frontend: stat-картки зверху сторінки статистики.

**SP:** 3

---

## Epic 2 — Особисті рекорди (PR)

### GYM-7: Логіка визначення PR

**User story:** Як користувач, я хочу, щоб система автоматично визначала мої
особисті рекорди по кожній вправі.

**Acceptance criteria:**

- Для кожної вправи: `max_weight` (+ reps при ній), `max_reps` (+ вага),
  `estimated_1rm` за Epley: `weight * (1 + reps / 30)`, і `achieved_at` для
  кожного з трьох.
- Чиста функція `calculate_prs(sets) -> dict[str, PRRecord]` у
  `src/services/statistics.py`, unit-тести на формулу і вибір максимумів.

**SP:** 3

### GYM-8: API + UI — вкладка рекордів

**User story:** Як користувач, я хочу відкрити список своїх рекордів по всіх
вправах, щоб планувати наступні цілі.

**Acceptance criteria:**

- `GET /api/statistics/records` — список `{exercise, muscle_group, max_weight,
  max_reps, estimated_1rm, achieved_at}`.
- Вкладка «Рекорди» на `/statistics`: картки, сортування за групою м'язів
  або алфавітом; свіжі рекорди (≤ 7 днів) підсвічуються.

**SP:** 5

### GYM-9: Сповіщення власнику про новий рекорд

**User story:** Як користувач, я хочу отримати повідомлення в боті одразу
після тренування, якщо я побив особистий рекорд.

**Acceptance criteria:**

- Після запису сесії в БД (GYM-2) викликається `calculate_prs` по всіх сетах
  вправ цієї сесії; рекорд вважається новим, якщо його `achieved_at` належить
  щойно збереженій сесії. Одна вибірка, без порівняння «до/після».
- Повідомлення `🏆 Новий рекорд! <вправа>: <вага> кг × <повторення>`
  надсилається на `telegram_id` **власника** тренування (user з
  `body["user"]`), а не того, хто відкрив WebApp.
- Non-critical: помилка не впливає на збереження (try/except, як у
  `_sync_workout_to_calendar`).

**SP:** 5

---

## Epic 3 — Історія / календар тренувань

### GYM-10: API — список сесій користувача

**User story:** Як користувач, я хочу переглянути список минулих тренувань
(дата, група м'язів, тривалість, кількість підходів).

**Acceptance criteria:**

- `GET /api/statistics/history?limit=&offset=` — сесії з підсумками
  (`exercises_count`, `sets_count`, `total_volume`, `duration_minutes`),
  найновіші першими.
- `GET /api/statistics/history/{session_id}` — вправи → підходи сесії.

**SP:** 3

### GYM-11: UI — вкладка «Історія» з деталізацією

**User story:** Як користувач, я хочу натиснути на тренування в історії і
побачити повний перелік вправ і підходів цього дня.

**Acceptance criteria:**

- Список карток за датою; клік розгортає деталі (вправа → вага × повтори),
  у стилі `workout.html`.
- «Завантажити ще» для пагінації.

**SP:** 5

---

## Epic 4 — Стрік і досягнення

### GYM-12: Розрахунок стріку тренувань

**User story:** Як користувач, я хочу бачити скільки тижнів поспіль я
тренуюсь стабільно.

**Acceptance criteria:**

- Стрік = кількість послідовних ISO-тижнів (у `settings.timezone`) з хоча б
  однією сесією. **Поточний незавершений тиждень без тренувань стрік не
  обриває**; обриває лише повністю пропущений завершений тиждень.
- `GET /api/statistics/streak` → `{current_streak, longest_streak, unit: "week"}`.
- `calculate_streak(session_dates, today) -> dict` — чиста функція, тести на:
  пропуск тижня, порожній список, поточний тиждень без тренувань, тренування
  на межі тижня (неділя/понеділок).

**SP:** 3

### GYM-13a: Досягнення — розблокування та збереження

**User story:** Як користувач, я хочу отримувати значки за досягнення, щоб
гейміфікувати процес.

**Acceptance criteria:**

- Фіксований список у коді: `WORKOUTS_10`, `WORKOUTS_50`, `WORKOUTS_100`,
  `STREAK_4_WEEKS`, `STREAK_12_WEEKS`, `FIRST_PR`, `VOLUME_10T`.
- Таблиця `user_achievements` (`user_id`, `achievement_code`, `unlocked_at`,
  unique по парі) + міграція.
- `AchievementsService.check_and_unlock(user_id)` після збереження сесії
  (разом із PR-перевіркою); нове досягнення → повідомлення власнику.
- Тести на кожну умову розблокування.

**SP:** 5

### GYM-13b: Досягнення — UI

**Acceptance criteria:**

- `GET /api/statistics/achievements` — усі досягнення з `unlocked: bool`,
  `unlocked_at`.
- Вкладка «Досягнення»: отримані — кольорові, невідримані — сірі з підказкою
  умови; блок стріку зверху (`current_streak` / `longest_streak`).

**SP:** 3

---

## Epic 5 — Статистика харчування

> Дані вже в БД (`daily_nutrition`), нової моделі не потрібно.

### GYM-14: API — тренди калорій/БЖВ за тиждень/місяць

**User story:** Як користувач, я хочу бачити графік споживання калорій і
БЖВ за тиждень/місяць.

**Acceptance criteria:**

- `GET /api/nutrition/statistics?period=week|month` → `by_day:
  [{date, calories, protein, fats, carbs, water_ml}]`, підсумовано з усіх
  записів дня; дні без записів — нулі.
- Межі днів — у `settings.timezone` (записи зберігаються в UTC через
  `utcnow()`).

**Технічні підзадачі:**

- Backend: `DailyNutritionRepository.get_totals_by_range(user_id, start, end)`
  (за зразком `get_today_total`, `src/database/repository.py:597`).
- Backend: `api_get_nutrition_statistics`.

**SP:** 5

### GYM-15: UI — статистика харчування

**Acceptance criteria:**

- Вкладка «Статистика» всередині `nutrition.html` (окрема сторінка не
  потрібна — менше навігації).
- Графік калорій за період з горизонтальною лінією цілі
  (`daily_calories` з профілю); перемикач тиждень/місяць; stacked-bar БЖВ.

**SP:** 5

### GYM-16: Порівняння план/факт та інсайт

**Acceptance criteria:**

- У відповіді GYM-14 — `avg_vs_goal: {calories_diff_pct, protein_diff_pct,
  fats_diff_pct, carbs_diff_pct}` на основі `Profile.daily_*`; дні без
  записів у середнє не входять.
- Текстовий інсайт над графіком («В середньому −12% від цілі по білку
  цього тижня»).

**SP:** 3

---

## Наскрізні задачі

- **GYM-17** — Підключити Chart.js один раз: перевірити, чи `Caddyfile`/CSP
  не блокують CDN; якщо є сумніви — вендорити `chart.umd.min.js` у
  `src/webapp/templates/` (уже роздається як `/static`). **SP: 2**
- **GYM-18** — Навігація: кнопка `📊 Статистика` у `get_main_menu_keyboard`
  (`src/bot/keyboards.py`) і команда `/statistics`, що відкривають
  `WebAppInfo(url=f"{webapp_url}/statistics")`. **SP: 2**
- **GYM-19** — Інтеграційні тести ендпоінтів `/api/statistics/*` через
  `aiohttp` test client (unit-тести логіки — в DoD кожного таска). **SP: 3**
- **GYM-20** — Оновити `README.md` (розділ «Функціонал», структура проєкту,
  таблиці БД). **SP: 1**

---

## MVP (≈ 33 SP)

Мінімальний набір, що дає робочу статистику на реальних історичних даних:

| Таск | SP |
| ---- | -- |
| GYM-0 auth-декоратор | 2 |
| GYM-1 моделі + міграція | 3 |
| GYM-2 запис у БД | 5 |
| GYM-2b бекфіл | 5 |
| GYM-17 Chart.js | 2 |
| GYM-3 сторінка `/statistics` | 5 |
| GYM-4 об'єм | 5 |
| GYM-6 активність | 3 |
| GYM-18 навігація | 2 |
| GYM-20 README | 1 |

Решта епіків додається інкрементально, кожен — самодостатній реліз.

## Рекомендована послідовність (sprint order)

1. **Sprint 1:** GYM-0, GYM-1, GYM-2, GYM-2b, GYM-17 — фундамент + бекфіл
2. **Sprint 2:** GYM-3, GYM-4, GYM-6, GYM-18, GYM-20 — MVP статистики
3. **Sprint 3:** GYM-5a, GYM-5b, GYM-7, GYM-8, GYM-9 — прогрес по вправі + PR
4. **Sprint 4:** GYM-10, GYM-11, GYM-19 — історія + інтеграційні тести
5. **Sprint 5:** GYM-12, GYM-13a, GYM-13b — стрік і досягнення
6. **Sprint 6:** GYM-14, GYM-15, GYM-16 — статистика харчування

## Відкриті питання та ризики

- **`is_admin()` заглушений** (`workout_program.py:58`) — будь-який
  користувач може відкрити програму/лог будь-якого username. Поза скоупом
  цього плану, але статистика успадкує цю дірку: `?user=<username>` на
  `/statistics` покаже чужі дані. Мінімум — у GYM-3 дозволяти `?user` лише
  якщо `telegram_id` ∈ `settings.admin_user_ids`.
- **Username як ключ Sheets.** Зміна Telegram-username розриває зв'язок з
  аркушами `Логи (<old>)`/`Програми (<old>)`. У БД зв'язок через GUID
  стабільний; для Sheets потрібне окреме рішення (перейменування аркуша при
  зміні username або зберігання «sheet name» у профілі) — окремий таск поза
  цим планом.
- **Sheets як джерело істини для програм** лишається; БД — лише логи та
  статистика. Повний відхід від Sheets — окремий епік.
- **Одиниця стріку — тиждень** (реалістично для 3–4 тренувань/тиждень).
  Якщо потрібен денний стрік — змінюється лише `calculate_streak`.
