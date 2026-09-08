"""Database models for the gym bot."""

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator, CHAR

from src.utils.datetime_utils import utcnow


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class GUID(TypeDecorator):
    """Platform-independent GUID type.

    Uses PostgreSQL's UUID type, otherwise uses CHAR(36), storing as stringified hex values.
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID())
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return str(value)
        else:
            if not isinstance(value, uuid.UUID):
                return str(uuid.UUID(value))
            else:
                return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if not isinstance(value, uuid.UUID):
                return uuid.UUID(value)
            return value


class BookingStatus(str, Enum):
    """Status of a booking."""

    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    ATTENDED = "attended"
    NO_SHOW = "no_show"


class TrainingType(str, Enum):
    """Type of training session."""

    GROUP = "group"
    PERSONAL = "personal"
    OPEN = "open"


class Gender(str, Enum):
    """Gender options for user profile."""

    MALE = "male"
    FEMALE = "female"


class Profile(Base):
    """User profile model with nutrition and body data."""

    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(              # noqa: A003
        GUID, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id"), unique=True, nullable=False, index=True
    )

    # Body data
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Daily nutrition goals
    daily_water_ml: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=2500
    )
    daily_calories: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=2500
    )
    daily_protein: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=150
    )
    daily_fats: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=80
    )
    daily_carbs: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=250
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="profile")

    def __repr__(self) -> str:
        return f"<Profile(id={self.id}, user_id={self.user_id})>"


class User(Base):
    """User model representing a Telegram user."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)               # noqa: A003
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # GYM-2: DB is the source of truth for workout logs; Sheets is an
    # opt-in mirror toggled from the WebApp settings screen.
    sync_workout_to_sheets: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    # Relationships
    profile: Mapped["Profile"] = relationship("Profile", back_populates="user", uselist=False)
    bookings: Mapped[list["Booking"]] = relationship("Booking", back_populates="user")
    daily_nutrition: Mapped[list["DailyNutrition"]] = relationship(
        "DailyNutrition", back_populates="user"
    )
    workout_sessions: Mapped[list["WorkoutSession"]] = relationship(
        "WorkoutSession", back_populates="user"
    )

    @property
    def full_name(self) -> str:
        """Get user's full name."""
        if self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name

    def __repr__(self) -> str:
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, name={self.full_name})>"


class Training(Base):
    """Training session model."""

    __tablename__ = "trainings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)              # noqa: A003
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    training_type: Mapped[str] = mapped_column(String(50), default=TrainingType.GROUP.value)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60)
    max_participants: Mapped[int] = mapped_column(Integer, default=10)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    google_calendar_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    # Relationships
    bookings: Mapped[list["Booking"]] = relationship("Booking", back_populates="training")

    @property
    def available_spots(self) -> int:
        """Calculate available spots for the training."""
        confirmed_bookings = [
            b for b in self.bookings if b.status == BookingStatus.CONFIRMED.value
        ]
        return max(0, self.max_participants - len(confirmed_bookings))

    @property
    def is_full(self) -> bool:
        """Check if training is fully booked."""
        return self.available_spots == 0

    def __repr__(self) -> str:
        return f"<Training(id={self.id}, title={self.title}, at={self.scheduled_at})>"


class Booking(Base):
    """Booking model linking users to trainings."""

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)              # noqa: A003
    user_id: Mapped[uuid.UUID] = mapped_column(GUID, ForeignKey("users.id"), nullable=False)
    training_id: Mapped[int] = mapped_column(Integer, ForeignKey("trainings.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default=BookingStatus.CONFIRMED.value)
    reminder_24h_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_2h_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="bookings")
    training: Mapped["Training"] = relationship("Training", back_populates="bookings")

    def __repr__(self) -> str:
        return f"<Booking(id={self.id}, user_id={self.user_id}, training_id={self.training_id})>"


class DailyNutrition(Base):
    """Daily nutrition tracking model."""

    __tablename__ = "daily_nutrition"

    id: Mapped[int] = mapped_column(                        # noqa: A003
        Integer, primary_key=True, autoincrement=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id"), nullable=False, index=True
    )
    date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True
    )

    # Water intake in milliliters
    water_ml: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=0
    )

    # Macronutrients
    calories: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=0
    )
    protein: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=0
    )
    fats: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=0
    )
    carbs: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=0
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    # Relationship
    user: Mapped["User"] = relationship(
        "User", back_populates="daily_nutrition"
    )

    def __repr__(self) -> str:
        date_str = self.date.date() if self.date else None
        return (
            f"<DailyNutrition(id={self.id}, "
            f"user_id={self.user_id}, date={date_str})>"
        )


class WorkoutSession(Base):
    """A single workout session (one visit to the gym).

    Owns the sets performed during it. A session is the unit used for
    history, streaks and duration; two workouts on the same day are kept as
    separate sessions rather than merged.
    """

    __tablename__ = "workout_sessions"
    __table_args__ = (
        Index("ix_workout_sessions_user_id_performed_at", "user_id", "performed_at"),
    )

    id: Mapped[int] = mapped_column(                        # noqa: A003
        Integer, primary_key=True, autoincrement=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id"), nullable=False, index=True
    )
    day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    muscle_group: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="workout_sessions")
    sets: Mapped[list["WorkoutSet"]] = relationship(
        "WorkoutSet", back_populates="session", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<WorkoutSession(id={self.id}, user_id={self.user_id}, "
            f"performed_at={self.performed_at})>"
        )


class WorkoutSet(Base):
    """A single logged set within a workout session."""

    __tablename__ = "workout_sets"
    __table_args__ = (
        Index(
            "ix_workout_sets_user_id_exercise_name_performed_at",
            "user_id", "exercise_name", "performed_at",
        ),
    )

    id: Mapped[int] = mapped_column(                        # noqa: A003
        Integer, primary_key=True, autoincrement=True
    )
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("workout_sessions.id"), nullable=False, index=True
    )
    # Denormalized from the session for fast per-user/per-exercise lookups
    # without a join.
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id"), nullable=False, index=True
    )
    exercise_name: Mapped[str] = mapped_column(String(255), nullable=False)
    muscle_group: Mapped[str | None] = mapped_column(String(255), nullable=True)
    set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_sets_reps: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Duplicated from the session so exercise-history queries can filter by
    # date without joining workout_sessions.
    performed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Relationships
    session: Mapped["WorkoutSession"] = relationship("WorkoutSession", back_populates="sets")
    user: Mapped["User"] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<WorkoutSet(id={self.id}, exercise_name={self.exercise_name}, "
            f"weight={self.weight}, reps={self.reps})>"
        )
