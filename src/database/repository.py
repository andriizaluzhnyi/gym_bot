"""Repository pattern for database operations."""

import uuid
from datetime import datetime

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
)


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
                    Training.scheduled_at > datetime.utcnow(),
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

        now = datetime.utcnow()
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

    async def create(self, user_id: int, training_id: int) -> Booking:
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

    async def get_user_upcoming_bookings(self, user_id: int) -> list[Booking]:
        """Get user's upcoming bookings."""
        result = await self.session.execute(
            select(Booking)
            .options(selectinload(Booking.training))
            .join(Training)
            .where(
                and_(
                    Booking.user_id == user_id,
                    Booking.status == BookingStatus.CONFIRMED.value,
                    Training.scheduled_at > datetime.utcnow(),
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
            record.updated_at = datetime.utcnow()
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

