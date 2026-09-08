"""Repository pattern for database operations."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models import (
    Booking,
    BookingStatus,
    DailyNutrition,
    Profile,
    Training,
    User,
    WorkoutSession,
    WorkoutSet,
)
from src.utils.datetime_utils import utcnow

# How long a draft (in-progress) workout session stays resumable before it's
# treated as abandoned. See WorkoutSessionRepository.get_active_draft.
DRAFT_SESSION_MAX_AGE = timedelta(hours=24)


class UserRepository:
    """Repository for User operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        """Get user by Telegram ID."""
        result = await self.session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        """Get user by Telegram username.

        Used to resolve the *owner* of a workout log (``body["user"]``),
        which may differ from the ``telegram_id`` in ``initData`` when a
        trainer logs a workout on behalf of a client.
        """
        result = await self.session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        telegram_id: int,
        first_name: str,
        last_name: str | None = None,
        username: str | None = None,
    ) -> tuple[User, bool]:
        """Get existing user or create a new one."""
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            # Update user info if changed
            user.first_name = first_name
            user.last_name = last_name
            user.username = username
            return user, False

        user = User(
            telegram_id=telegram_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
        )
        self.session.add(user)
        await self.session.flush()
        return user, True

    async def update_phone(self, telegram_id: int, phone: str) -> User | None:
        """Update user's phone number."""
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            user.phone = phone
            await self.session.flush()
        return user

    async def set_admin(self, telegram_id: int, is_admin: bool = True) -> User | None:
        """Set user as admin."""
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            user.is_admin = is_admin
            await self.session.flush()
        return user

    async def set_sync_workout_to_sheets(
        self, telegram_id: int, enabled: bool
    ) -> User | None:
        """Toggle whether workout logs are also mirrored to Google Sheets.

        The DB is always the primary store (GYM-2); this only controls the
        optional duplicate write, configured from the WebApp settings screen.
        """
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            user.sync_workout_to_sheets = enabled
            await self.session.flush()
        return user

    async def get_all_with_notifications(self) -> list[User]:
        """Get all users with notifications enabled."""
        result = await self.session.execute(
            select(User).where(
                and_(User.is_active == True, User.notifications_enabled == True)  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def get_all_with_username(self) -> list[User]:
        """Get all users that have a username set."""
        result = await self.session.execute(
            select(User).where(
                and_(User.is_active == True, User.username.isnot(None))  # noqa: E712
            ).order_by(User.username)
        )
        return list(result.scalars().all())

    async def update_nutrition_settings(
        self,
        telegram_id: int,
        age: int | None = None,
        height: float | None = None,
        weight: float | None = None,
        gender: str | None = None,
        daily_water_ml: int | None = None,
        daily_calories: int | None = None,
        daily_protein: int | None = None,
        daily_fats: int | None = None,
        daily_carbs: int | None = None,
    ) -> User | None:
        """Update user's nutrition and body settings.

        Deprecated: Use ProfileRepository instead.
        This method is kept for backward compatibility.
        """
        user = await self.get_by_telegram_id(telegram_id)
        if not user:
            return None

        # Get or create profile
        profile_repo = ProfileRepository(self.session)
        await profile_repo.get_or_create(user.id)

        # Update profile
        await profile_repo.update(
            user.id,
            age=age,
            height=height,
            weight=weight,
            gender=gender,
            daily_water_ml=daily_water_ml,
            daily_calories=daily_calories,
            daily_protein=daily_protein,
            daily_fats=daily_fats,
            daily_carbs=daily_carbs,
        )

        await self.session.flush()
        return user

    async def get_nutrition_settings(self, telegram_id: int) -> dict | None:
        """Get user's nutrition settings as dictionary.

        Deprecated: Use ProfileRepository instead.
        This method is kept for backward compatibility.
        """
        user = await self.get_by_telegram_id(telegram_id)
        if not user:
            return None

        profile_repo = ProfileRepository(self.session)
        profile = await profile_repo.get_by_user_id(user.id)

        if not profile:
            # Return defaults
            return {
                "age": None,
                "height": None,
                "weight": None,
                "gender": None,
                "daily_water_ml": 2500,
                "daily_calories": 2500,
                "daily_protein": 150,
                "daily_fats": 80,
                "daily_carbs": 250,
            }

        return {
            "age": profile.age,
            "height": profile.height,
            "weight": profile.weight,
            "gender": profile.gender,
            "daily_water_ml": profile.daily_water_ml or 2500,
            "daily_calories": profile.daily_calories or 2500,
            "daily_protein": profile.daily_protein or 150,
            "daily_fats": profile.daily_fats or 80,
            "daily_carbs": profile.daily_carbs or 250,
        }


class ProfileRepository:
    """Repository for Profile operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(self, user_id: uuid.UUID) -> Profile | None:
        """Get profile by user ID."""
        result = await self.session.execute(
            select(Profile).where(Profile.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, user_id: uuid.UUID) -> tuple[Profile, bool]:
        """Get existing profile or create a new one."""
        profile = await self.get_by_user_id(user_id)
        if profile:
            return profile, False

        profile = Profile(user_id=user_id)
        self.session.add(profile)
        await self.session.flush()
        return profile, True

    async def update(
        self,
        user_id: uuid.UUID,
        age: int | None = None,
        height: float | None = None,
        weight: float | None = None,
        gender: str | None = None,
        daily_water_ml: int | None = None,
        daily_calories: int | None = None,
        daily_protein: int | None = None,
        daily_fats: int | None = None,
        daily_carbs: int | None = None,
    ) -> Profile | None:
        """Update profile settings.

        Only updates fields that are not None.
        """
        profile = await self.get_by_user_id(user_id)
        if not profile:
            return None

        if age is not None:
            profile.age = age
        if height is not None:
            profile.height = height
        if weight is not None:
            profile.weight = weight
        if gender is not None:
            profile.gender = gender
        if daily_water_ml is not None:
            profile.daily_water_ml = daily_water_ml
        if daily_calories is not None:
            profile.daily_calories = daily_calories
        if daily_protein is not None:
            profile.daily_protein = daily_protein
        if daily_fats is not None:
            profile.daily_fats = daily_fats
        if daily_carbs is not None:
            profile.daily_carbs = daily_carbs

        await self.session.flush()
        return profile

    async def get_settings(self, user_id: uuid.UUID) -> dict | None:
        """Get profile settings as dictionary."""
        profile = await self.get_by_user_id(user_id)
        if not profile:
            return None

        return {
            "age": profile.age,
            "height": profile.height,
            "weight": profile.weight,
            "gender": profile.gender,
            "daily_water_ml": profile.daily_water_ml or 2500,
            "daily_calories": profile.daily_calories or 2500,
            "daily_protein": profile.daily_protein or 150,
            "daily_fats": profile.daily_fats or 80,
            "daily_carbs": profile.daily_carbs or 250,
        }


class TrainingRepository:
    """Repository for Training operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, training_id: int) -> Training | None:
        """Get training by ID."""
        result = await self.session.execute(
            select(Training)
            .options(selectinload(Training.bookings).selectinload(Booking.user))
            .where(Training.id == training_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        title: str,
        scheduled_at: datetime,
        description: str | None = None,
        training_type: str = "group",
        duration_minutes: int = 60,
        max_participants: int = 10,
        location: str | None = None,
    ) -> Training:
        """Create a new training session."""
        training = Training(
            title=title,
            description=description,
            training_type=training_type,
            scheduled_at=scheduled_at,
            duration_minutes=duration_minutes,
            max_participants=max_participants,
            location=location,
        )
        self.session.add(training)
        await self.session.flush()
        return training

    async def get_upcoming(self, limit: int = 10) -> list[Training]:
        """Get upcoming trainings."""
        result = await self.session.execute(
            select(Training)
            .options(selectinload(Training.bookings))
            .where(
                and_(
                    Training.scheduled_at > utcnow(),
                    Training.is_cancelled == False,  # noqa: E712
                )
            )
            .order_by(Training.scheduled_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_for_date(self, date: datetime) -> list[Training]:
        """Get trainings for a specific date."""
        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)

        result = await self.session.execute(
            select(Training)
            .options(selectinload(Training.bookings))
            .where(
                and_(
                    Training.scheduled_at >= start_of_day,
                    Training.scheduled_at <= end_of_day,
                    Training.is_cancelled == False,  # noqa: E712
                )
            )
            .order_by(Training.scheduled_at)
        )
        return list(result.scalars().all())

    async def cancel(self, training_id: int) -> Training | None:
        """Cancel a training."""
        training = await self.get_by_id(training_id)
        if training:
            training.is_cancelled = True
            await self.session.flush()
        return training

    async def update_google_event_id(
        self, training_id: int, google_event_id: str
    ) -> Training | None:
        """Update Google Calendar event ID."""
        training = await self.get_by_id(training_id)
        if training:
            training.google_calendar_event_id = google_event_id
            await self.session.flush()
        return training

    async def get_trainings_for_reminder(
        self, hours_before: int, reminder_field: str
    ) -> list[Training]:
        """Get trainings that need reminder notifications."""
        from datetime import timedelta

        now = utcnow()
        target_time = now + timedelta(hours=hours_before)
        window_start = target_time - timedelta(minutes=30)
        window_end = target_time + timedelta(minutes=30)

        result = await self.session.execute(
            select(Training)
            .options(selectinload(Training.bookings).selectinload(Booking.user))
            .where(
                and_(
                    Training.scheduled_at >= window_start,
                    Training.scheduled_at <= window_end,
                    Training.is_cancelled == False,  # noqa: E712
                )
            )
        )
        return list(result.scalars().all())


class BookingRepository:
    """Repository for Booking operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, booking_id: int) -> Booking | None:
        """Get booking by ID."""
        result = await self.session.execute(
            select(Booking)
            .options(selectinload(Booking.user), selectinload(Booking.training))
            .where(Booking.id == booking_id)
        )
        return result.scalar_one_or_none()

    async def create(self, user_id: uuid.UUID, training_id: int) -> Booking:
        """Create a new booking."""
        booking = Booking(
            user_id=user_id,
            training_id=training_id,
            status=BookingStatus.CONFIRMED.value,
        )
        self.session.add(booking)
        await self.session.flush()
        return booking

    async def get_user_booking_for_training(
        self, user_id: uuid.UUID, training_id: int
    ) -> Booking | None:
        """Get user's booking for a specific training."""
        result = await self.session.execute(
            select(Booking).where(
                and_(
                    Booking.user_id == user_id,
                    Booking.training_id == training_id,
                    Booking.status == BookingStatus.CONFIRMED.value,
                )
            )
        )
        return result.scalar_one_or_none()

    async def cancel(self, booking_id: int) -> Booking | None:
        """Cancel a booking."""
        booking = await self.get_by_id(booking_id)
        if booking:
            booking.status = BookingStatus.CANCELLED.value
            await self.session.flush()
        return booking

    async def get_user_upcoming_bookings(self, user_id: uuid.UUID) -> list[Booking]:
        """Get user's upcoming bookings."""
        result = await self.session.execute(
            select(Booking)
            .options(selectinload(Booking.training))
            .join(Training)
            .where(
                and_(
                    Booking.user_id == user_id,
                    Booking.status == BookingStatus.CONFIRMED.value,
                    Training.scheduled_at > utcnow(),
                    Training.is_cancelled == False,  # noqa: E712
                )
            )
            .order_by(Training.scheduled_at)
        )
        return list(result.scalars().all())

    async def mark_reminder_sent(
        self, booking_id: int, reminder_type: str
    ) -> Booking | None:
        """Mark a reminder as sent."""
        booking = await self.get_by_id(booking_id)
        if booking:
            if reminder_type == "24h":
                booking.reminder_24h_sent = True
            elif reminder_type == "2h":
                booking.reminder_2h_sent = True
            await self.session.flush()
        return booking

    async def mark_attendance(
        self, booking_id: int, attended: bool = True
    ) -> Booking | None:
        """Mark attendance for a booking."""
        booking = await self.get_by_id(booking_id)
        if booking:
            booking.status = (
                BookingStatus.ATTENDED.value if attended else BookingStatus.NO_SHOW.value
            )
            await self.session.flush()
        return booking

    async def get_training_participants(self, training_id: int) -> list[Booking]:
        """Get all confirmed bookings for a training."""
        result = await self.session.execute(
            select(Booking)
            .options(selectinload(Booking.user))
            .where(
                and_(
                    Booking.training_id == training_id,
                    Booking.status == BookingStatus.CONFIRMED.value,
                )
            )
        )
        return list(result.scalars().all())


class DailyNutritionRepository:
    """Repository for DailyNutrition operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_and_date(
        self, user_id: uuid.UUID, date: datetime
    ) -> DailyNutrition | None:
        """Get daily nutrition record for a specific user and date."""
        # Normalize to start of day
        date_normalized = date.replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        result = await self.session.execute(
            select(DailyNutrition).where(
                and_(
                    DailyNutrition.user_id == user_id,
                    DailyNutrition.date == date_normalized,
                )
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        user_id: uuid.UUID,
        date: datetime,
        water_ml: int | None = None,
        calories: int | None = None,
        protein: int | None = None,
        fats: int | None = None,
        carbs: int | None = None,
    ) -> DailyNutrition:
        """Create new daily nutrition record."""
        # Use current timestamp (not normalized to start of day)
        record = DailyNutrition(
            user_id=user_id,
            date=date,
            water_ml=water_ml or 0,
            calories=calories or 0,
            protein=protein or 0,
            fats=fats or 0,
            carbs=carbs or 0,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def create_or_update(
        self,
        user_id: uuid.UUID,
        date: datetime,
        water_ml: int | None = None,
        calories: int | None = None,
        protein: int | None = None,
        fats: int | None = None,
        carbs: int | None = None,
    ) -> DailyNutrition:
        """Create or update daily nutrition record."""
        # Normalize to start of day
        date_normalized = date.replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # Try to get existing record
        record = await self.get_by_user_and_date(user_id, date_normalized)

        if record:
            # Update existing record
            if water_ml is not None:
                record.water_ml = water_ml
            if calories is not None:
                record.calories = calories
            if protein is not None:
                record.protein = protein
            if fats is not None:
                record.fats = fats
            if carbs is not None:
                record.carbs = carbs
            record.updated_at = utcnow()
        else:
            # Create new record
            record = DailyNutrition(
                user_id=user_id,
                date=date_normalized,
                water_ml=water_ml or 0,
                calories=calories or 0,
                protein=protein or 0,
                fats=fats or 0,
                carbs=carbs or 0,
            )
            self.session.add(record)

        await self.session.flush()
        return record

    async def get_user_history(
        self, user_id: uuid.UUID, limit: int = 30
    ) -> list[DailyNutrition]:
        """Get user's nutrition history, most recent first."""
        result = await self.session.execute(
            select(DailyNutrition)
            .where(DailyNutrition.user_id == user_id)
            .order_by(DailyNutrition.date.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_today_total(
        self, user_id: uuid.UUID, date: datetime
    ) -> dict:
        """Get total nutrition for today (sum of all records)."""
        from sqlalchemy import func

        # Normalize to start of day
        start_of_day = date.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_of_day = date.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

        result = await self.session.execute(
            select(
                func.sum(DailyNutrition.water_ml).label('water_ml'),
                func.sum(DailyNutrition.calories).label('calories'),
                func.sum(DailyNutrition.protein).label('protein'),
                func.sum(DailyNutrition.fats).label('fats'),
                func.sum(DailyNutrition.carbs).label('carbs'),
            )
            .where(
                and_(
                    DailyNutrition.user_id == user_id,
                    DailyNutrition.date >= start_of_day,
                    DailyNutrition.date <= end_of_day,
                )
            )
        )
        row = result.one()

        return {
            'water_ml': row.water_ml or 0,
            'calories': row.calories or 0,
            'protein': row.protein or 0,
            'fats': row.fats or 0,
            'carbs': row.carbs or 0,
        }


class WorkoutSessionRepository:
    """Repository for WorkoutSession operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_session_with_sets(
        self,
        user_id: uuid.UUID,
        performed_at: datetime,
        sets: list[dict],
        day: int | None = None,
        muscle_group: str | None = None,
        duration_seconds: int | None = None,
    ) -> WorkoutSession:
        """Atomically create an already-*completed* workout session.

        ``sets`` is a list of dicts with ``exercise_name``, ``weight``,
        ``reps``, ``set_number``, and optionally ``muscle_group``,
        ``planned_sets_reps`` and ``performed_at`` (defaults to the
        session's ``performed_at``, e.g. for backfilled per-row timestamps).
        Everything is added in a single flush, i.e. one transaction.

        This is the one-shot fallback path used when no draft session exists
        (see ``start_draft_session`` / GYM-2c) — e.g. an older client, or the
        draft autosave never having run. ``completed_at`` is set to
        ``performed_at`` immediately since there was no separate draft phase.
        """
        workout_session = WorkoutSession(
            user_id=user_id,
            performed_at=performed_at,
            completed_at=performed_at,
            day=day,
            muscle_group=muscle_group,
            duration_seconds=duration_seconds,
        )
        self.session.add(workout_session)
        await self.session.flush()

        for set_data in sets:
            self.session.add(
                WorkoutSet(
                    session_id=workout_session.id,
                    user_id=user_id,
                    exercise_name=set_data["exercise_name"],
                    muscle_group=set_data.get("muscle_group"),
                    set_number=set_data["set_number"],
                    weight=set_data["weight"],
                    reps=set_data["reps"],
                    planned_sets_reps=set_data.get("planned_sets_reps"),
                    performed_at=set_data.get("performed_at", performed_at),
                )
            )

        await self.session.flush()
        return workout_session

    async def get_by_id(self, session_id: int) -> WorkoutSession | None:
        """Get a session by its primary key (sets not eagerly loaded)."""
        return await self.session.get(WorkoutSession, session_id)

    async def get_by_id_with_sets(
        self, session_id: int
    ) -> WorkoutSession | None:
        """Get a session by its primary key with its sets eagerly loaded —
        used by the history detail endpoint (GYM-10), where per-set data is
        read after the request-scoped session that fetched it is gone.
        """
        result = await self.session.execute(
            select(WorkoutSession)
            .where(WorkoutSession.id == session_id)
            .options(selectinload(WorkoutSession.sets))
        )
        return result.scalar_one_or_none()

    async def get_active_draft(
        self,
        user_id: uuid.UUID,
        day: int | None = None,
        muscle_group: str | None = None,
        max_age: timedelta = DRAFT_SESSION_MAX_AGE,
    ) -> WorkoutSession | None:
        """Get the most recent unfinished (``completed_at is None``) session
        for this user/day/muscle combo, started within ``max_age``.

        Used to resume an in-progress workout from the DB (GYM-2c) instead
        of the browser's ``localStorage``. A draft older than ``max_age`` is
        treated as abandoned and not returned (the caller will start a new
        one); it is left in the DB rather than deleted.
        """
        conditions = [
            WorkoutSession.user_id == user_id,
            WorkoutSession.completed_at.is_(None),
            WorkoutSession.performed_at >= utcnow() - max_age,
            WorkoutSession.day == day
            if day is not None
            else WorkoutSession.day.is_(None),
            WorkoutSession.muscle_group == muscle_group
            if muscle_group is not None
            else WorkoutSession.muscle_group.is_(None),
        ]

        result = await self.session.execute(
            select(WorkoutSession)
            .where(and_(*conditions))
            .options(selectinload(WorkoutSession.sets))
            .order_by(WorkoutSession.performed_at.desc())
        )
        return result.scalars().first()

    async def start_draft_session(
        self,
        user_id: uuid.UUID,
        day: int | None = None,
        muscle_group: str | None = None,
    ) -> WorkoutSession:
        """Create a new draft session (``completed_at is None``) with no sets
        yet — called as soon as the WebApp opens to start a workout, so the
        DB (not ``localStorage``) becomes the source of truth from the
        start.
        """
        workout_session = WorkoutSession(
            user_id=user_id,
            performed_at=utcnow(),
            day=day,
            muscle_group=muscle_group,
        )
        self.session.add(workout_session)
        await self.session.flush()
        return workout_session

    async def complete_session(
        self,
        session_id: int,
        user_id: uuid.UUID,
        duration_seconds: int | None = None,
        day: int | None = None,
        muscle_group: str | None = None,
    ) -> WorkoutSession | None:
        """Mark a draft session as finished.

        Returns ``None`` if the session doesn't exist or belongs to a
        different user. Idempotent: calling it again on an already-completed
        session just updates ``duration_seconds``/``day``/``muscle_group`
        without touching ``completed_at`` a second time.
        """
        workout_session = await self.get_by_id(session_id)
        if workout_session is None or workout_session.user_id != user_id:
            return None

        if workout_session.completed_at is None:
            workout_session.completed_at = utcnow()
        if duration_seconds is not None:
            workout_session.duration_seconds = duration_seconds
        if day is not None:
            workout_session.day = day
        if muscle_group is not None:
            workout_session.muscle_group = muscle_group

        await self.session.flush()
        return workout_session

    async def get_sessions_by_period(
        self,
        user_id: uuid.UUID,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[WorkoutSession]:
        """Get a user's *completed* sessions (sets eagerly loaded) in a time
        range. Draft (in-progress) sessions are excluded.

        ``start``/``end`` are inclusive UTC bounds; omit either for an
        open-ended range. Most recent first.
        """
        conditions = [
            WorkoutSession.user_id == user_id,
            WorkoutSession.completed_at.isnot(None),
        ]
        if start is not None:
            conditions.append(WorkoutSession.performed_at >= start)
        if end is not None:
            conditions.append(WorkoutSession.performed_at <= end)

        result = await self.session.execute(
            select(WorkoutSession)
            .where(and_(*conditions))
            .options(selectinload(WorkoutSession.sets))
            .order_by(WorkoutSession.performed_at.desc())
        )
        return list(result.scalars().all())

    async def get_history_page(
        self,
        user_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> list[WorkoutSession]:
        """Get one page of a user's *completed* sessions (sets eagerly
        loaded), most recent first — GYM-10's history list. Same
        "completed only" filter as ``get_sessions_by_period``, but paged at
        the SQL level (``limit``/``offset``) instead of loading the whole
        history, since the history list has no natural time bound.
        """
        result = await self.session.execute(
            select(WorkoutSession)
            .where(
                and_(
                    WorkoutSession.user_id == user_id,
                    WorkoutSession.completed_at.isnot(None),
                )
            )
            .options(selectinload(WorkoutSession.sets))
            .order_by(WorkoutSession.performed_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class WorkoutSetRepository:
    """Repository for WorkoutSet operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_sets_by_user_and_exercise(
        self,
        user_id: uuid.UUID,
        exercise_name: str,
        limit: int | None = None,
    ) -> list[WorkoutSet]:
        """Get a user's sets for one exercise from *completed* sessions,
        ordered by date (oldest first). Sets from an in-progress draft
        session are excluded, same as ``get_sessions_by_period``.
        """
        query = (
            select(WorkoutSet)
            .join(WorkoutSession, WorkoutSet.session_id == WorkoutSession.id)
            .where(
                and_(
                    WorkoutSet.user_id == user_id,
                    WorkoutSet.exercise_name == exercise_name,
                    WorkoutSession.completed_at.isnot(None),
                )
            )
            .order_by(WorkoutSet.performed_at.asc())
        )
        if limit is not None:
            query = query.limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_distinct_exercises(
        self, user_id: uuid.UUID
    ) -> list[dict]:
        """Unique exercises the user has logged, from *completed* sessions
        (GYM-5a) — one ``{exercise_name, muscle_group}`` per exercise, sorted
        by ``muscle_group`` then ``exercise_name`` (ready for a grouped
        dropdown, GYM-5b).

        ``muscle_group`` can drift for the same exercise across logs (e.g. a
        program edit), so this uses each exercise's *most recent* value
        rather than an arbitrary one.
        """
        query = (
            select(
                WorkoutSet.exercise_name,
                WorkoutSet.muscle_group,
                WorkoutSet.performed_at,
            )
            .join(WorkoutSession, WorkoutSet.session_id == WorkoutSession.id)
            .where(
                and_(
                    WorkoutSet.user_id == user_id,
                    WorkoutSession.completed_at.isnot(None),
                )
            )
            .order_by(WorkoutSet.performed_at.asc())
        )
        result = await self.session.execute(query)

        # Ascending order means the last write for a given exercise_name is
        # its most recent muscle_group.
        latest_muscle: dict[str, str | None] = {}
        for exercise_name, muscle_group, _performed_at in result.all():
            latest_muscle[exercise_name] = muscle_group

        return [
            {'exercise_name': name, 'muscle_group': muscle}
            for name, muscle in sorted(
                latest_muscle.items(), key=lambda item: (item[1] or '', item[0])
            )
        ]

    async def replace_exercise_sets(
        self,
        session_id: int,
        user_id: uuid.UUID,
        exercise_name: str,
        sets: list[dict],
        muscle_group: str | None = None,
        planned_sets_reps: str | None = None,
        performed_at: datetime | None = None,
    ) -> None:
        """Replace all of one exercise's sets within a session with ``sets``.

        Used to autosave a draft session (GYM-2c): the WebApp always sends
        the exercise's *full* current set list (it renumbers sets after a
        removal), so delete-then-recreate is simpler and safer than trying
        to patch individual rows by ``set_number`` and keeps numbering
        contiguous for free. ``sets`` is a list of dicts with
        ``set_number``, ``weight``, ``reps``.
        """
        existing = await self.session.execute(
            select(WorkoutSet).where(
                WorkoutSet.session_id == session_id,
                WorkoutSet.exercise_name == exercise_name,
            )
        )
        for row in existing.scalars().all():
            await self.session.delete(row)
        await self.session.flush()

        for set_data in sets:
            self.session.add(
                WorkoutSet(
                    session_id=session_id,
                    user_id=user_id,
                    exercise_name=exercise_name,
                    muscle_group=muscle_group,
                    set_number=set_data["set_number"],
                    weight=set_data["weight"],
                    reps=set_data["reps"],
                    planned_sets_reps=planned_sets_reps,
                    performed_at=performed_at or utcnow(),
                )
            )

        await self.session.flush()
