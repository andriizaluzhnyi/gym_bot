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


class NutritionEntryType(str, Enum):
    """What a ``DailyNutrition`` row logs (GYM-21)."""

    WATER = "water"
    MEAL = "meal"


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
    # GYM-25: lets a user hide the water card/tracking entirely without
    # losing their daily_water_ml goal — re-enabling restores it unchanged.
    water_tracking_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
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
    """Daily nutrition tracking model.

    Each row is one logged entry — one water increment (``entry_type ==
    "water"``) or one meal (``entry_type == "meal"``); "today"'s totals and
    meal list are the sum/filter of every row for a user on a given day,
    not one row per day. ``entry_type`` used to be inferred from
    ``water_ml == 0`` at query time (GYM-21); it's now an explicit column so
    a meal that happens to log zero macros can't be misread as a water
    entry, and so a meal can carry a name.
    """

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
    entry_type: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    meal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

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

    A session with ``completed_at is None`` is a *draft*: created as soon as
    the WebApp is opened to start/resume a workout (GYM-2c), so the DB is the
    source of truth for the in-progress log, not just the finished one.
    ``performed_at`` is therefore the session's *start* time; it stays fixed
    once set, while ``completed_at`` is filled in when the workout is
    finished. History/statistics queries should only consider sessions where
    ``completed_at is not None``.
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
    # NULL while the workout is still in progress (a draft); set once the
    # user finishes it. See class docstring.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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


class UserAchievement(Base):
    """One achievement badge a user has unlocked (GYM-13a).

    ``achievement_code`` is one of ``AchievementsService``'s fixed catalog
    codes (``WORKOUTS_10``, ``STREAK_4_WEEKS``, ...) — not a foreign key,
    since the catalog lives in code (``src/services/achievements.py``),
    not a DB table. Once unlocked, a row is never removed or re-evaluated:
    achievements are permanent, even if e.g. a streak later breaks.
    """

    __tablename__ = "user_achievements"
    __table_args__ = (
        Index(
            "ix_user_achievements_user_id_achievement_code",
            "user_id", "achievement_code",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(                        # noqa: A003
        Integer, primary_key=True, autoincrement=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id"), nullable=False, index=True
    )
    achievement_code: Mapped[str] = mapped_column(String(50), nullable=False)
    unlocked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    # Relationship
    user: Mapped["User"] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<UserAchievement(user_id={self.user_id}, "
            f"code={self.achievement_code})>"
        )


class Exercise(Base):
    """Catalog entry for one exercise (GYM-27).

    Shared across every user's programs, de-duplicated by
    ``normalized_name`` (``src/services/exercise_names.py``) so "Жим
    лежачи" and "жим лежачи " land on the same row instead of two. Media
    fields (``description``/``image_url``/``video_url``) are optional and
    filled in later (GYM-31) — this task only adds the schema, nothing
    populates them yet.
    """

    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(                        # noqa: A003
        Integer, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    muscle_group: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    video_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:
        return f"<Exercise(id={self.id}, name={self.name})>"


class WorkoutProgramExercise(Base):
    """One exercise entry within a user's workout program for a given day
    (GYM-27) — the DB-backed replacement for a row in the "Програми
    (<user>)" Google Sheet; GYM-28 wires the bot/WebApp to write here
    instead of (or in addition to) Sheets.

    ``muscle_group`` is a plain snapshot string (the emoji-prefixed labels
    from ``MUSCLE_GROUPS``, e.g. "🏋️ Груди"), not a foreign key — there's
    no muscle-group catalog table, same as ``WorkoutSession``/
    ``WorkoutSet``. ``exercise_name`` is likewise a snapshot of
    ``Exercise.name`` at the time this row was added (alongside the real
    ``exercise_id`` FK), so a later rename of the catalog entry doesn't
    silently rewrite what a program said on the day it was created —
    matches how ``WorkoutSet.exercise_name`` already works relative to
    logged sets.
    """

    __tablename__ = "workout_program_exercises"
    __table_args__ = (
        Index(
            "ix_workout_program_exercises_user_id_day_position",
            "user_id", "day", "position",
        ),
    )

    id: Mapped[int] = mapped_column(                        # noqa: A003
        Integer, primary_key=True, autoincrement=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id"), nullable=False, index=True
    )
    day: Mapped[int] = mapped_column(Integer, nullable=False)
    muscle_group: Mapped[str] = mapped_column(String(255), nullable=False)
    exercise_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("exercises.id"), nullable=False, index=True
    )
    exercise_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sets_reps: Mapped[str] = mapped_column(String(50), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Relationships
    user: Mapped["User"] = relationship("User")
    exercise: Mapped["Exercise"] = relationship("Exercise")

    def __repr__(self) -> str:
        return (
            f"<WorkoutProgramExercise(id={self.id}, user_id={self.user_id}, "
            f"day={self.day}, exercise_name={self.exercise_name})>"
        )
