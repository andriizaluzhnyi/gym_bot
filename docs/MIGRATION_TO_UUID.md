# Міграція: Перехід на UUID для ідентифікаторів користувачів

## Що було зроблено

Змінено тип primary key для таблиці `users` з автоінкрементного Integer на UUID:
- **users.id**: `INTEGER AUTOINCREMENT` → `UUID/CHAR(36)`
- **Всі foreign keys** що посилаються на users.id також змінені на UUID

## Зміни в структурі бази даних

### Таблиця `users`
- **id**: `CHAR(36)` PRIMARY KEY (UUID) - замість `INTEGER AUTOINCREMENT`
- Решта полів без змін

### Таблиця `profiles`
- **id**: `CHAR(36)` PRIMARY KEY (UUID)
- **user_id**: `CHAR(36)` FOREIGN KEY (UUID) → users.id

### Таблиця `bookings`
- **id**: залишається `INTEGER AUTOINCREMENT`
- **user_id**: `CHAR(36)` FOREIGN KEY (UUID) → users.id
- **training_id**: залишається `INTEGER`

### Таблиця `daily_nutrition`
- **id**: залишається `INTEGER AUTOINCREMENT`
- **user_id**: `CHAR(36)` FOREIGN KEY (UUID) → users.id

### Таблиця `user_id_mapping` (нова, допоміжна)
- **old_id**: `INTEGER` - старий ID користувача
- **new_uuid**: `CHAR(36)` - новий UUID
- Використовується для відстеження відповідності старих ID новим UUID

## Зміни в коді

### Моделі (src/database/models.py)
1. Додано імпорт uuid
2. Створено клас `GUID` - універсальний тип для UUID (підтримує PostgreSQL і SQLite)
3. Оновлено типи:
   - `User.id`: `Mapped[uuid.UUID]`
   - `Profile.id` і `Profile.user_id`: `Mapped[uuid.UUID]`
   - `Booking.user_id`: `Mapped[uuid.UUID]`
   - `DailyNutrition.user_id`: `Mapped[uuid.UUID]`

### Repository (src/database/repository.py)
Оновлено типи параметрів у всіх методах:
- `ProfileRepository`: всі методи з `user_id: int` → `user_id: uuid.UUID`
- `BookingRepository`: методи з `user_id: int` → `user_id: uuid.UUID`
- `DailyNutritionRepository`: методи з `user_id: int` → `user_id: uuid.UUID`

### Автоматична генерація UUID
UUID генерується автоматично при створенні нового користувача:
```python
id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
```

## Як запустити міграцію

```bash
# Активувати віртуальне оточення
.\venv\Scripts\Activate.ps1  # Windows PowerShell

# Запустити міграційний скрипт
python scripts/migrate_to_uuid.py
```

## Що робить міграційний скрипт

1. **Створює таблицю маппінгу** - для відповідності старих Integer ID новим UUID
2. **Генерує UUID** для кожного існуючого користувача
3. **Створює нові таблиці** з правильною структурою (UUID)
4. **Копіює дані** з старих таблиць в нові, підставляючи UUID
5. **Замінює таблиці** - видаляє старі, перейменовує нові
6. **Зберігає маппінг** - таблиця user_id_mapping залишається для довідки

## Результат міграції

```
INFO:__main__:Users table has 2 records
INFO:__main__:Sample user ID: 9d8aac77-0c03-42b6-b1b6-57570ce417a8 (type: str)
INFO:__main__:Profiles table has 1 records
INFO:__main__:Bookings table has 0 records
INFO:__main__:Daily nutrition table has 3 records
```

## Переваги UUID

1. **Глобальна унікальність** - UUID унікальні без координації між серверами
2. **Безпека** - неможливо передбачити наступний ID (на відміну від автоінкременту)
3. **Розподілені системи** - можна генерувати ID на клієнті
4. **Злиття даних** - легко об'єднувати дані з різних джерел без конфліктів
5. **Незалежність від БД** - UUID можна генерувати без звернення до бази даних

## Зворотна сумісність

Код використовує UUID прозоро - всі хендлери та API продовжують працювати без змін.
Репозиторії приймають та повертають UUID, але для зовнішнього коду це прозоро.

## SQLite vs PostgreSQL

**SQLite**: UUID зберігаються як `CHAR(36)` в форматі рядка
**PostgreSQL**: Використовується нативний тип `UUID`

Клас `GUID` автоматично обирає правильний тип в залежності від СУБД.

## Важливо

- UUID генеруються автоматично при створенні нових записів
- Старі Integer ID більше не використовуються
- Таблиця `user_id_mapping` зберігається для історії, її можна видалити пізніше
- Всі foreign keys оновлені для роботи з UUID
