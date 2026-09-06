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

**Ключове архітектурне рішення (Epic 0):** агрегації (сума об'єму за тиждень,
пошук PR, стріки) на Google Sheets API повільні, лімітовані квотами і не
підтримують SQL-агрегацію. Тому весь план будується на перенесенні логів
тренувань у БД, з опційним дублюючим записом у Sheets (щоб не ламати вже
існуючий експорт/перегляд програм).

## Огляд епіків

| Epic | Назва | SP | Пріоритет |
|---|---|---|---|
| 0 | Фундамент: лог тренувань у БД | 8 | Must (блокує все інше) |
| 1 | Статистика тренувань (WebApp) | 21 | Must |
| 2 | Особисті рекорди (PR) | 13 | Should |
| 3 | Історія / календар тренувань | 8 | Should |
| 4 | Стрік і досягнення | 8 | Could |
| 5 | Статистика харчування | 13 | Should |

Загалом: **71 SP**.

---

## Epic 0 — Фундамент: лог тренувань у БД

### GYM-1: Модель та міграція `WorkoutSet`
**User story:** Як розробник, я хочу зберігати кожен виконаний підхід у БД,
щоб мати можливість швидко агрегувати статистику без звернень до Google Sheets API.

**Acceptance criteria:**
- Нова таблиця `workout_sets` (або `workout_logs`) з полями: `id`, `user_id`
  (FK → `users.id`, GUID), `exercise_name`, `muscle_group`, `day` (int|null),
  `set_number`, `weight` (Float), `reps` (Integer), `planned_sets_reps`
  (String|null), `performed_at` (DateTime, index), `created_at`.
- Індекси: `(user_id, exercise_name, performed_at)`, `(user_id, performed_at)`.
- Alembic-міграція `alembic revision --autogenerate -m "add workout_sets table"`.

**Технічні підзадачі:**
- DB: додати клас `WorkoutSet(Base)` у `src/database/models.py` (за зразком
  `DailyNutrition`), relationship `User.workout_sets`.
- DB: згенерувати та перевірити міграцію в `alembic/versions/`.
- Backend: `WorkoutSetRepository` у `src/database/repository.py` — методи
  `create_bulk(user_id, sets)`, `get_by_user_and_exercises(...)`,
  `get_by_user_and_period(...)`.

**SP:** 3

### GYM-2: Запис у БД паралельно з Google Sheets
**User story:** Як користувач, я хочу, щоб мій лог тренування зберігався
надійно, навіть якщо це вимагає змін під капотом, і щоб історія в Sheets
залишалась доступною як і раніше.

**Acceptance criteria:**
- `api_save_workout_log` (`src/webapp/server.py`) після успішного запису в
  Sheets додатково пише ті самі сети в `workout_sets` через
  `WorkoutSetRepository.create_bulk`.
- Якщо запис у БД падає — лог у Sheets все одно зберігається (Sheets лишається
  джерелом істини для сумісності), помилка лише логується (аналогічно
  `_sync_workout_to_calendar`).
- Юніт-тест: збереження лога створює правильну кількість рядків у
  `workout_sets` з коректними `user_id`/вагами/повтореннями.

**Технічні підзадачі:**
- Backend: розширити `api_save_workout_log`, отримати `user.id` через
  `UserRepository.get_by_telegram_id`.
- Tests: `tests/` — тест на подвійний запис (мок Sheets + реальна тестова БД).

**SP:** 5

---

## Epic 1 — Статистика тренувань (WebApp)

### GYM-3: Сторінка `/statistics` у Mini App
**User story:** Як користувач, я хочу відкрити окрему сторінку статистики з
головного меню бота, щоб бачити свій прогрес по тренуваннях.

**Acceptance criteria:**
- Новий handler `statistics_handler` віддає `statistics.html`
  (`src/webapp/templates/statistics.html`), маршрут `GET /statistics`.
- Сторінка має вкладки: «Об'єм по м'язових групах», «Прогрес по вправі»,
  «Загальна активність» (кількість тренувань/тижнів).
- Дизайн і стилі відповідають існуючим (`workout.html`, `profile.html`) —
  темна/світла тема Telegram (`Telegram.WebApp.themeParams`).
- Кнопка в головному меню бота (`get_main_menu_keyboard`,
  `src/bot/keyboards.py`) або в `/profile`, що відкриває `WebAppInfo(url=f"{webapp_url}/statistics")`.

**Технічні підзадачі:**
- Frontend: `src/webapp/templates/statistics.html` (HTML/CSS/vanilla JS, за
  зразком `workout.html`), підключення легкої chart-бібліотеки (напр.
  `chart.js` через `<script src>` з CDN, без збірки).
- Backend: `statistics_handler` + реєстрація в `create_webapp()`.
- Bot: додати пункт меню / команду `/statistics`, кнопка `WebAppInfo`.

**SP:** 5

### GYM-4: API — об'єм тренувань за період і по м'язових групах
**User story:** Як користувач, я хочу бачити скільки тоннажу (вага × повтори)
я підняв за тиждень/місяць в розрізі груп м'язів, щоб оцінити баланс
навантаження.

**Acceptance criteria:**
- `GET /api/statistics/volume?period=week|month|all&muscle=<optional>` —
  повертає суму `weight * reps` згруповану по днях і по `muscle_group`.
- Авторизація через `Authorization: <initData>` (як в інших `/api/*`,
  `validate_telegram_webapp_data`).
- Порожні періоди повертають нулі, а не помилку.

**Технічні підзадачі:**
- Backend: `api_get_volume_statistics` у `src/webapp/server.py`, SQL-агрегація
  через `WorkoutSetRepository` (SQLAlchemy `func.sum`, `group_by`).
- Frontend: графік стовпчиками/лінією (Chart.js) на вкладці «Об'єм».

**SP:** 5

### GYM-5: API + UI — прогрес по конкретній вправі
**User story:** Як користувач, я хочу обрати вправу (напр. «Жим лежачи») і
побачити графік зміни робочої ваги/повторень у часі, щоб бачити прогрес.

**Acceptance criteria:**
- `GET /api/statistics/exercise-progress?exercise=<name>` — повертає список
  `{date, max_weight, total_reps, top_set: {weight, reps}}` по всіх
  тренуваннях з цією вправою, відсортовано за датою.
- Селектор вправи в UI підвантажує список унікальних вправ користувача
  (`GET /api/statistics/exercises`).
- Лінійний графік ваги і окремо — кількості повторень.

**Технічні підзадачі:**
- Backend: `api_get_exercise_progress`, `api_get_user_exercises` (DISTINCT
  `exercise_name` по `user_id`).
- Frontend: dropdown вибору вправи + два лінійні графіки.

**SP:** 8

### GYM-6: API — загальна активність (кількість тренувань, регулярність)
**User story:** Як користувач, я хочу бачити скільки тренувань я зробив за
тиждень/місяць і середню тривалість, щоб відстежувати регулярність.

**Acceptance criteria:**
- `GET /api/statistics/summary` — `{workouts_count, avg_duration_minutes,
  total_volume, most_trained_muscle}` за обраний період.
- `duration_seconds`, що вже передається в `api_save_workout_log`, зберігається
  окремо (у `workout_sets` через нове поле `session_duration_seconds` на рівні
  тренування, або окрема легка таблиця `workout_sessions` — на розсуд
  розробника під час реалізації).

**Технічні підзадачі:**
- DB (за потреби): невелика таблиця `workout_sessions` (`user_id`, `day`,
  `muscle_group`, `duration_seconds`, `performed_at`) — зв'язана з набором
  сетів, спрощує підрахунок кількості тренувань і тривалості.
- Backend: `api_get_statistics_summary`.
- Frontend: картки-показники (stat tiles) зверху сторінки статистики.

**SP:** 3

---

## Epic 2 — Особисті рекорди (PR)

### GYM-7: Логіка визначення PR
**User story:** Як користувач, я хочу, щоб система автоматично визначала мої
особисті рекорди по кожній вправі, щоб не рахувати вручну.

**Acceptance criteria:**
- Для кожної вправи рахуються: `max_weight` (макс. вага з будь-якою
  кількістю повторень), `max_reps` (макс. повторень з будь-якою вагою),
  оцінка `estimated_1rm` за формулою Epley: `weight * (1 + reps / 30)`.
- Функція чиста (unit-testable): приймає список сетів, повертає структуру PR.

**Технічні підзадачі:**
- Backend: `src/services/statistics.py` — `calculate_prs(sets: list[WorkoutSet]) -> dict`.
- Tests: перевірка формули Epley та вибору максимумів на прикладових даних.

**SP:** 3

### GYM-8: API + UI — сторінка/вкладка рекордів
**User story:** Як користувач, я хочу відкрити список своїх рекордів по всіх
вправах, щоб пишатися прогресом і планувати наступні цілі.

**Acceptance criteria:**
- `GET /api/statistics/records` — список `{exercise, muscle_group, max_weight,
  max_reps, estimated_1rm, achieved_at}` по всіх вправах користувача.
- Вкладка «Рекорди» на сторінці `/statistics` зі списком карток, сортування за
  групою м'язів або алфавітом.

**Технічні підзадачі:**
- Backend: `api_get_personal_records` (використовує `calculate_prs`).
- Frontend: список карток рекордів на `statistics.html`.

**SP:** 5

### GYM-9: Сповіщення про новий рекорд одразу після тренування
**User story:** Як користувач, я хочу отримати повідомлення в боті одразу
після завершення тренування, якщо я побив особистий рекорд, щоб відчути
мотивацію в моменті.

**Acceptance criteria:**
- Після `api_save_workout_log` порівнюється кожен збережений сет з попереднім
  PR (до збереження нового логу); якщо перевищено — бот надсилає повідомлення
  `🏆 Новий рекорд! <вправа>: <вага>кг × <повторення>`.
- Не блокує основний флоу збереження логу (аналогічно `_sync_workout_to_calendar`
  — non-critical, обгорнуто в try/except).

**Технічні підзадачі:**
- Backend: у `api_save_workout_log` — виклик `calculate_prs` до і після запису,
  діф, відправка `bot.send_message` з новими рекордами.

**SP:** 5

---

## Epic 3 — Історія / календар тренувань

### GYM-10: API — список тренувань користувача
**User story:** Як користувач, я хочу переглянути список своїх минулих
тренувань (дата, група м'язів, тривалість, кількість підходів), щоб бачити
історію.

**Acceptance criteria:**
- `GET /api/statistics/history?limit=&offset=` — список сесій, згрупованих за
  датою+днем програми, з підсумками (вправ, підходів, тоннаж).
- Пагінація (limit/offset або cursor).

**Технічні підзадачі:**
- Backend: `api_get_workout_history`, групування `workout_sets` по
  `(performed_at::date, day)`.

**SP:** 3

### GYM-11: UI — вкладка «Історія» з деталізацією дня
**User story:** Як користувач, я хочу натиснути на тренування в історії і
побачити повний перелік вправ і підходів цього дня, щоб згадати що робив.

**Acceptance criteria:**
- Список тренувань (картки за датою) на вкладці «Історія».
- Клік по картці розгортає деталі: вправа → підходи (вага × повтори),
  аналогічно вигляду в `workout.html`.

**Технічні підзадачі:**
- Frontend: розгортання/модалка деталей дня на `statistics.html`.
- Backend: `GET /api/statistics/history/{date}` (або параметр в тому ж
  ендпоінті) для деталей конкретного дня.

**SP:** 5

---

## Epic 4 — Стрік і досягнення

### GYM-12: Розрахунок стріку тренувань
**User story:** Як користувач, я хочу бачити скільки тижнів поспіль я
тренуюсь стабільно, щоб підтримувати мотивацію.

**Acceptance criteria:**
- Стрік = кількість послідовних тижнів (або днів — на вибір при реалізації),
  де є хоча б одне тренування, без пропуску.
- `GET /api/statistics/streak` → `{current_streak, longest_streak, unit: "week"}`.

**Технічні підзадачі:**
- Backend: `calculate_streak(sessions: list[date]) -> dict` в
  `src/services/statistics.py` + unit-тести на межові випадки (пропуск
  тижня, старт з нуля, поточний тиждень ще не завершено).

**SP:** 3

### GYM-13: Досягнення (badges)
**User story:** Як користувач, я хочу отримувати значки за досягнення (напр.
«10 тренувань», «Стрік 4 тижні», «Перший PR»), щоб гейміфікувати процес.

**Acceptance criteria:**
- Фіксований список досягнень (конфіг у коді, не в БД, на першому етапі):
  напр. `WORKOUTS_10`, `WORKOUTS_50`, `STREAK_4_WEEKS`, `FIRST_PR`.
- `GET /api/statistics/achievements` — список усіх досягнень з позначкою
  отримано/ні та датою отримання.
- Легка таблиця `user_achievements` (`user_id`, `achievement_code`,
  `unlocked_at`) для збереження факту розблокування (щоб не рахувати заново
  щоразу і коректно ловити «нове досягнення» для сповіщення).

**Технічні підзадачі:**
- DB: таблиця `user_achievements` + міграція.
- Backend: `AchievementsService.check_and_unlock(user_id)` — викликається
  після збереження тренування (як і PR-перевірка), надсилає сповіщення при
  розблокуванні нового досягнення.
- Frontend: вкладка/секція «Досягнення» з badge-іконками (отримані —
  кольорові, невідримані — сірі/заблоковані).

**SP:** 5

---

## Epic 5 — Статистика харчування

> Дані вже в БД (`daily_nutrition`), тому цей епік простіший за архітектурою —
> нової моделі не потрібно, лише агрегація існуючих записів.

### GYM-14: API — тренди калорій/БЖВ за тиждень/місяць
**User story:** Як користувач, я хочу бачити графік споживання калорій і
БЖВ за останній тиждень/місяць, щоб розуміти чи дотримуюсь плану.

**Acceptance criteria:**
- `GET /api/nutrition/statistics?period=week|month` — список
  `{date, calories, protein, fats, carbs, water_ml}` по днях, підсумовано з
  усіх записів дня (аналогічно `get_today_total`, але за діапазон дат).

**Технічні підзадачі:**
- Backend: `DailyNutritionRepository.get_totals_by_range(user_id, start, end)`
  (нова агрегація, за зразком наявного `get_user_history`/`get_today_total` у
  `src/database/repository.py:585`).
- Backend: `api_get_nutrition_statistics` у `src/webapp/server.py`.

**SP:** 5

### GYM-15: UI — сторінка/вкладка статистики харчування
**User story:** Як користувач, я хочу відкрити графіки харчування прямо з
Mini App нутриції, щоб не переключатись між різними екранами.

**Acceptance criteria:**
- Нова вкладка «Статистика» в `nutrition.html` (або окрема сторінка
  `/nutrition/statistics`, лінк з `nutrition.html`).
- Лінійний/стовпчиковий графік калорій за період з горизонтальною лінією
  цільового значення (`daily_calories` з профілю).
- Перемикач періоду (тиждень/місяць).

**Технічні підзадачі:**
- Frontend: розширення `src/webapp/templates/nutrition.html` або нова
  `nutrition_statistics.html`.
- Backend: маршрут, якщо окрема сторінка.

**SP:** 5

### GYM-16: Порівняння план/факт і короткий інсайт
**User story:** Як користувач, я хочу бачити наскільки в середньому я
відхиляюсь від цілі по калоріях/білку за тиждень, щоб коригувати харчування.

**Acceptance criteria:**
- У відповіді `api_get_nutrition_statistics` додається `avg_vs_goal`:
  `{calories_diff_pct, protein_diff_pct, ...}`.
- У UI — короткий текстовий інсайт (напр. «В середньому −12% від цілі по
  білку цього тижня»).

**Технічні підзадачі:**
- Backend: розрахунок відхилення в `api_get_nutrition_statistics` на основі
  `Profile.daily_calories/daily_protein/...`.
- Frontend: текстовий блок-інсайт над графіком.

**SP:** 3

---

## Наскрізні (cross-cutting) задачі

- **GYM-17** — Обрати та підключити легку JS-бібліотеку графіків (Chart.js
  через CDN) один раз, перевикористовувати на `statistics.html` і в
  nutrition-статистиці. **SP: 2**
- **GYM-18** — Пункт навігації: кнопка/команда `📊 Статистика` в головному
  меню бота (`src/bot/keyboards.py`, `src/bot/handlers/start.py`), що відкриває
  `WebAppInfo(url=f"{webapp_url}/statistics")`. **SP: 2**
- **GYM-19** — Unit-тести на всю розрахункову логіку
  (`src/services/statistics.py`: PR, стрік, агрегації) в `tests/`. **SP: 5**
- **GYM-20** — Оновити `README.md` (розділ «Функціонал» і структура проєкту)
  після додавання нових сторінок/ендпоінтів. **SP: 1**

---

## Рекомендована послідовність виконання (sprint order)

1. **Sprint 1:** GYM-1, GYM-2 (фундамент БД) + GYM-17 (chart-бібліотека)
2. **Sprint 2:** GYM-3, GYM-4, GYM-6, GYM-18 (базова сторінка статистики +
   об'єм + навігація)
3. **Sprint 3:** GYM-5 (прогрес по вправі) + GYM-7, GYM-8, GYM-9 (PR)
4. **Sprint 4:** GYM-10, GYM-11 (історія) + GYM-19 (тести)
5. **Sprint 5:** GYM-12, GYM-13 (стрік/досягнення)
6. **Sprint 6:** GYM-14, GYM-15, GYM-16 (статистика харчування) + GYM-20 (доки)

## Відкриті питання (потребують рішення перед стартом)

- Чи лишати Google Sheets як джерело для перегляду/редагування програм
  (`Програми (<user>)`), а БД використовувати лише для логів/статистики? —
  План вище саме так і припускає (Sheets не чіпаємо, лог дублюємо в БД).
- Одиниця стріку — тиждень чи день? (В плані закладено тиждень як менш
  строгий і реалістичніший для графіку тренувань 3-4 рази/тиждень.)
- Чи потрібна окрема сторінка `/nutrition/statistics`, чи вкладка всередині
  `nutrition.html` (впливає на GYM-15).
