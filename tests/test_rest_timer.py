"""Unit tests for GYM-47's ``should_send_rest_reminder``
(``src/services/rest_timer.py``) — the pure yes/no rule the scheduled rest-
timer reminder checks right before it would fire.
"""

from datetime import datetime

from src.database.models import WorkoutSession
from src.services.rest_timer import should_send_rest_reminder


class TestShouldSendRestReminder:
    def test_missing_session_does_not_send(self):
        # Re-read via `session_id` came back empty (shouldn't normally
        # happen — sessions aren't deleted — but treated defensively.
        assert should_send_rest_reminder(None) is False

    def test_active_draft_still_sends(self):
        session = WorkoutSession(completed_at=None)
        assert should_send_rest_reminder(session) is True

    def test_completed_session_does_not_send(self):
        session = WorkoutSession(completed_at=datetime(2024, 1, 1, 12, 0, 0))
        assert should_send_rest_reminder(session) is False
