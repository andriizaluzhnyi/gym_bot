"""Google Sheets integration service."""

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config import get_settings

if TYPE_CHECKING:
    from src.database.models import Booking, Training, User

settings = get_settings()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class GoogleSheetsService:
    """Service for managing Google Sheets data."""

    def __init__(self):
        self.spreadsheet_id = settings.google_spreadsheet_id
        self.credentials_file = settings.google_credentials_file
        self._service = None

    def _get_service(self):
        """Get or create Google Sheets service."""
        if self._service is None:
            if not self.credentials_file.exists():
                raise FileNotFoundError(
                    f"Google credentials file not found: {self.credentials_file}"
                )

            credentials = Credentials.from_service_account_file(
                str(self.credentials_file),
                scopes=SCOPES,
            )
            self._service = build("sheets", "v4", credentials=credentials)

        return self._service

    async def _ensure_sheets_exist(self) -> None:
        """Ensure required sheets exist in the spreadsheet."""
        if not self.spreadsheet_id:
            return

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            # Get existing sheets
            spreadsheet = await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .get(spreadsheetId=self.spreadsheet_id)
                .execute(),
            )

            existing_sheets = {
                sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])
            }

            required_sheets = ["Тренування", "Записи", "Відвідування", "Програми"]
            sheets_to_create = [s for s in required_sheets if s not in existing_sheets]

            if sheets_to_create:
                requests = [
                    {"addSheet": {"properties": {"title": title}}} for title in sheets_to_create
                ]

                await loop.run_in_executor(
                    None,
                    lambda: service.spreadsheets()
                    .batchUpdate(spreadsheetId=self.spreadsheet_id, body={"requests": requests})
                    .execute(),
                )

                # Add headers to new sheets
                await self._add_headers()

        except Exception as e:
            print(f"Error ensuring sheets exist: {e}")

    async def _add_headers(self) -> None:
        """Add headers to sheets."""
        if not self.spreadsheet_id:
            return

        headers = {
            "Тренування": [
                ["ID", "Назва", "Дата", "Час", "Тривалість", "Місць", "Місце", "Статус"]
            ],
            "Записи": [
                [
                    "ID",
                    "Користувач",
                    "Telegram ID",
                    "Телефон",
                    "Тренування",
                    "Дата",
                    "Статус",
                    "Дата запису",
                ]
            ],
            "Відвідування": [
                ["Дата", "Тренування", "Учасник", "Telegram", "Присутність"]
            ],
            "Програми": [
                ["День", "Група м'язів", "Вправа", "Підходи", "Повторення", "Коментар", "Дата"]
            ],
        }

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            for sheet_name, header_rows in headers.items():
                await loop.run_in_executor(
                    None,
                    lambda sn=sheet_name, hr=header_rows: service.spreadsheets()
                    .values()
                    .update(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"{sn}!A1",
                        valueInputOption="RAW",
                        body={"values": hr},
                    )
                    .execute(),
                )

        except Exception as e:
            print(f"Error adding headers: {e}")

    async def add_training_record(self, training: "Training") -> bool:
        """Add a training record to the Trainings sheet.

        Args:
            training: Training model instance

        Returns:
            True if successful, False otherwise
        """
        if not self.spreadsheet_id:
            return False

        try:
            await self._ensure_sheets_exist()

            service = self._get_service()
            loop = asyncio.get_event_loop()

            date_str = training.scheduled_at.strftime("%d.%m.%Y")
            time_str = training.scheduled_at.strftime("%H:%M")

            row = [
                str(training.id),
                training.title,
                date_str,
                time_str,
                str(training.duration_minutes),
                str(training.max_participants),
                training.location or "",
                "Активне",
            ]

            await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self.spreadsheet_id,
                    range="Тренування!A:H",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row]},
                )
                .execute(),
            )

            return True

        except HttpError as e:
            print(f"Google Sheets API error: {e}")
            return False
        except Exception as e:
            print(f"Error adding training record: {e}")
            return False

    async def add_booking_record(
        self,
        booking: "Booking",
        user: "User",
        training: "Training",
    ) -> bool:
        """Add a booking record to the Bookings sheet.

        Args:
            booking: Booking model instance
            user: User model instance
            training: Training model instance

        Returns:
            True if successful, False otherwise
        """
        if not self.spreadsheet_id:
            return False

        try:
            await self._ensure_sheets_exist()

            service = self._get_service()
            loop = asyncio.get_event_loop()

            date_str = training.scheduled_at.strftime("%d.%m.%Y %H:%M")
            created_str = datetime.utcnow().strftime("%d.%m.%Y %H:%M")

            row = [
                str(booking.id),
                user.full_name,
                str(user.telegram_id),
                user.phone or "",
                training.title,
                date_str,
                "Підтверджено",
                created_str,
            ]

            await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self.spreadsheet_id,
                    range="Записи!A:H",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row]},
                )
                .execute(),
            )

            return True

        except HttpError as e:
            print(f"Google Sheets API error: {e}")
            return False
        except Exception as e:
            print(f"Error adding booking record: {e}")
            return False

    async def update_booking_status(self, booking_id: int, status: str) -> bool:
        """Update booking status in the sheet.

        Args:
            booking_id: Booking ID
            status: New status

        Returns:
            True if successful, False otherwise
        """
        if not self.spreadsheet_id:
            return False

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            # Find the row with this booking ID
            result = await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range="Записи!A:H")
                .execute(),
            )

            values = result.get("values", [])
            row_index = None

            for i, row in enumerate(values):
                if row and row[0] == str(booking_id):
                    row_index = i + 1  # 1-indexed
                    break

            if row_index:
                status_map = {
                    "confirmed": "Підтверджено",
                    "cancelled": "Скасовано",
                    "attended": "Присутній",
                    "no_show": "Не з'явився",
                }

                await loop.run_in_executor(
                    None,
                    lambda: service.spreadsheets()
                    .values()
                    .update(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"Записи!G{row_index}",
                        valueInputOption="RAW",
                        body={"values": [[status_map.get(status, status)]]},
                    )
                    .execute(),
                )

            return True

        except HttpError as e:
            print(f"Google Sheets API error: {e}")
            return False
        except Exception as e:
            print(f"Error updating booking status: {e}")
            return False

    async def add_attendance_record(
        self,
        training: "Training",
        user: "User",
        attended: bool,
    ) -> bool:
        """Add attendance record.

        Args:
            training: Training model instance
            user: User model instance
            attended: Whether user attended

        Returns:
            True if successful, False otherwise
        """
        if not self.spreadsheet_id:
            return False

        try:
            await self._ensure_sheets_exist()

            service = self._get_service()
            loop = asyncio.get_event_loop()

            date_str = training.scheduled_at.strftime("%d.%m.%Y")
            attendance_str = "Так" if attended else "Ні"

            row = [
                date_str,
                training.title,
                user.full_name,
                f"@{user.username}" if user.username else str(user.telegram_id),
                attendance_str,
            ]

            await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self.spreadsheet_id,
                    range="Відвідування!A:E",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row]},
                )
                .execute(),
            )

            return True

        except HttpError as e:
            print(f"Google Sheets API error: {e}")
            return False
        except Exception as e:
            print(f"Error adding attendance record: {e}")
            return False

    async def add_workout_program(self, exercises: list[dict]) -> bool:
        """Add workout program exercises to the Programs sheet.

        Args:
            exercises: List of exercise dictionaries with 'day' field

        Returns:
            True if successful, False otherwise
        """
        if not self.spreadsheet_id:
            return False

        try:
            await self._ensure_sheets_exist()

            service = self._get_service()
            loop = asyncio.get_event_loop()

            rows = []
            for ex in exercises:
                row = [
                    str(ex.get("day", 1)),
                    ex.get("muscle_group", ""),
                    ex.get("exercise", ""),
                    str(ex.get("sets", "")),
                    str(ex.get("reps", "")),
                    ex.get("comment", ""),
                    ex.get("created_at", datetime.now().strftime("%d.%m.%Y %H:%M")),
                ]
                rows.append(row)

            await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self.spreadsheet_id,
                    range="Програми!A:G",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": rows},
                )
                .execute(),
            )

            return True

        except HttpError as e:
            print(f"Google Sheets API error: {e}")
            return False
        except Exception as e:
            print(f"Error adding workout program: {e}")
            return False

    async def get_workout_programs(self, limit: int = 50) -> list[dict]:
        """Get workout programs from the Programs sheet.

        Args:
            limit: Maximum number of records to return

        Returns:
            List of program dictionaries
        """
        if not self.spreadsheet_id:
            return []

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            result = await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range="Програми!A:G")
                .execute(),
            )

            values = result.get("values", [])

            # Skip header row
            if len(values) <= 1:
                return []

            programs = []
            for row in values[1:]:  # Skip header
                if len(row) >= 4:
                    programs.append({
                        "day": row[0] if len(row) > 0 else "1",
                        "muscle_group": row[1] if len(row) > 1 else "",
                        "exercise": row[2] if len(row) > 2 else "",
                        "sets": row[3] if len(row) > 3 else "",
                        "reps": row[4] if len(row) > 4 else "",
                        "comment": row[5] if len(row) > 5 else "",
                        "created_at": row[6] if len(row) > 6 else "",
                    })

            return programs[-limit:] if limit else programs

        except HttpError as e:
            print(f"Google Sheets API error: {e}")
            return []
        except Exception as e:
            print(f"Error getting workout programs: {e}")
            return []

    async def get_last_program_day(self) -> int:
        """Get the last day number from Programs sheet.

        Returns:
            Last day number or 0 if no programs exist
        """
        if not self.spreadsheet_id:
            return 0

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            result = await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range="Програми!A:A")
                .execute(),
            )

            values = result.get("values", [])

            # Skip header, find max day number
            if len(values) <= 1:
                return 0

            max_day = 0
            for row in values[1:]:
                if row and row[0]:
                    try:
                        day = int(row[0])
                        if day > max_day:
                            max_day = day
                    except ValueError:
                        continue

            return max_day

        except HttpError as e:
            print(f"Google Sheets API error: {e}")
            return 0
        except Exception as e:
            print(f"Error getting last program day: {e}")
            return 0

    async def get_last_program_day_for_muscle_group(self, muscle_group: str) -> int:
        """Get the last day number for a specific muscle group.

        Args:
            muscle_group: The muscle group to filter by

        Returns:
            Last day number for this muscle group or 0 if none exist
        """
        if not self.spreadsheet_id:
            return 0

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            # Get columns A (Day) and B (Muscle Group)
            result = await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range="Програми!A:B")
                .execute(),
            )

            values = result.get("values", [])

            # Skip header, find max day number for this muscle group
            if len(values) <= 1:
                return 0

            max_day = 0
            for row in values[1:]:
                if len(row) >= 2 and row[0] and row[1]:
                    if row[1] == muscle_group:
                        try:
                            day = int(row[0])
                            if day > max_day:
                                max_day = day
                        except ValueError:
                            continue

            return max_day

        except HttpError as e:
            print(f"Google Sheets API error: {e}")
            return 0
        except Exception as e:
            print(f"Error getting last program day for muscle group: {e}")
            return 0
