"""Tests for database models."""

import pytest
from datetime import datetime

from src.database.models import User, Training, Booking, BookingStatus


class TestUserModel:
    """Tests for User model."""

    def test_full_name_with_last_name(self):
        """Test full_name property with last name."""
        user = User(
            telegram_id=123456,
            first_name="Іван",
            last_name="Петренко",
        )
        assert user.full_name == "Іван Петренко"

    def test_full_name_without_last_name(self):
        """Test full_name property without last name."""
        user = User(
            telegram_id=123456,
            first_name="Іван",
        )
        assert user.full_name == "Іван"


class TestTrainingModel:
    """Tests for Training model."""

    def test_available_spots_empty(self):
        """Test available spots with no bookings."""
        training = Training(
            title="Силове тренування",
            scheduled_at=datetime.now(),
            max_participants=10,
        )
        training.bookings = []
        assert training.available_spots == 10
        assert training.is_full is False

    def test_is_full(self):
        """Test is_full property."""
        training = Training(
            title="Силове тренування",
            scheduled_at=datetime.now(),
            max_participants=2,
        )
        # Create mock bookings
        booking1 = Booking(user_id=1, training_id=1, status=BookingStatus.CONFIRMED.value)
        booking2 = Booking(user_id=2, training_id=1, status=BookingStatus.CONFIRMED.value)
        training.bookings = [booking1, booking2]

        assert training.available_spots == 0
        assert training.is_full is True


class TestBookingStatus:
    """Tests for BookingStatus enum."""

    def test_status_values(self):
        """Test booking status values."""
        assert BookingStatus.CONFIRMED.value == "confirmed"
        assert BookingStatus.CANCELLED.value == "cancelled"
        assert BookingStatus.ATTENDED.value == "attended"
        assert BookingStatus.NO_SHOW.value == "no_show"
