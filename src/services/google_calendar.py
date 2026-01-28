"""Google Calendar integration service."""

import asyncio
import base64
import json
from datetime import timedelta
from typing import TYPE_CHECKING

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import get_settings

if TYPE_CHECKING:
    from src.database.models import Training

settings = get_settings()

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarService:
    """Service for managing Google Calendar events."""

    def __init__(self):
        self.calendar_id = settings.google_calendar_id
        self.credentials_base64 = settings.google_credentials_file_base64
        self._service = None

    def _get_service(self):
        """Get or create Google Calendar service."""
        if self._service is None:
            if not self.credentials_base64:
                raise ValueError("Google credentials not configured")

            # Decode base64 credentials
            credentials_json = base64.b64decode(self.credentials_base64).decode('utf-8')
            credentials_info = json.loads(credentials_json)

            credentials = Credentials.from_service_account_info(
                credentials_info,
                scopes=SCOPES,
            )
            self._service = build("calendar", "v3", credentials=credentials)

        return self._service

    async def create_event(self, training: "Training") -> str | None:
        """Create a calendar event for a training.

        Args:
            training: Training model instance

        Returns:
            Google Calendar event ID or None if failed
        """
        if not self.calendar_id:
            return None

        try:
            service = self._get_service()

            end_time = training.scheduled_at + timedelta(minutes=training.duration_minutes)

            event = {
                "summary": f"🏋️ {training.title}",
                "description": training.description or "",
                "location": training.location or "",
                "start": {
                    "dateTime": training.scheduled_at.isoformat(),
                    "timeZone": settings.timezone,
                },
                "end": {
                    "dateTime": end_time.isoformat(),
                    "timeZone": settings.timezone,
                },
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "popup", "minutes": 24 * 60},
                        {"method": "popup", "minutes": 120},
                    ],
                },
            }

            # Run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: service.events()
                .insert(calendarId=self.calendar_id, body=event)
                .execute(),
            )

            return result.get("id")

        except HttpError as e:
            print(f"Google Calendar API error: {e}")
            return None
        except Exception as e:
            print(f"Error creating calendar event: {e}")
            return None

    async def update_event(
        self,
        event_id: str,
        training: "Training",
    ) -> bool:
        """Update an existing calendar event.

        Args:
            event_id: Google Calendar event ID
            training: Updated training model

        Returns:
            True if successful, False otherwise
        """
        if not self.calendar_id or not event_id:
            return False

        try:
            service = self._get_service()

            end_time = training.scheduled_at + timedelta(minutes=training.duration_minutes)

            event = {
                "summary": f"🏋️ {training.title}",
                "description": training.description or "",
                "location": training.location or "",
                "start": {
                    "dateTime": training.scheduled_at.isoformat(),
                    "timeZone": settings.timezone,
                },
                "end": {
                    "dateTime": end_time.isoformat(),
                    "timeZone": settings.timezone,
                },
            }

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: service.events()
                .update(calendarId=self.calendar_id, eventId=event_id, body=event)
                .execute(),
            )

            return True

        except HttpError as e:
            print(f"Google Calendar API error: {e}")
            return False
        except Exception as e:
            print(f"Error updating calendar event: {e}")
            return False

    async def delete_event(self, event_id: str) -> bool:
        """Delete a calendar event.

        Args:
            event_id: Google Calendar event ID

        Returns:
            True if successful, False otherwise
        """
        if not self.calendar_id or not event_id:
            return False

        try:
            service = self._get_service()

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: service.events()
                .delete(calendarId=self.calendar_id, eventId=event_id)
                .execute(),
            )

            return True

        except HttpError as e:
            print(f"Google Calendar API error: {e}")
            return False
        except Exception as e:
            print(f"Error deleting calendar event: {e}")
            return False

    async def add_attendee(self, event_id: str, email: str) -> bool:
        """Add an attendee to a calendar event.

        Args:
            event_id: Google Calendar event ID
            email: Attendee email

        Returns:
            True if successful, False otherwise
        """
        if not self.calendar_id or not event_id:
            return False

        try:
            service = self._get_service()

            loop = asyncio.get_event_loop()

            # Get current event
            event = await loop.run_in_executor(
                None,
                lambda: service.events()
                .get(calendarId=self.calendar_id, eventId=event_id)
                .execute(),
            )

            # Add attendee
            attendees = event.get("attendees", [])
            attendees.append({"email": email})
            event["attendees"] = attendees

            # Update event
            await loop.run_in_executor(
                None,
                lambda: service.events()
                .update(calendarId=self.calendar_id, eventId=event_id, body=event)
                .execute(),
            )

            return True

        except HttpError as e:
            print(f"Google Calendar API error: {e}")
            return False
        except Exception as e:
            print(f"Error adding attendee: {e}")
            return False
