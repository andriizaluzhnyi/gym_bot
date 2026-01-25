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

            required_sheets = [
                "Тренування",
                "Записи",
                "Відвідування",
                "Програми",
                "Програми (Візуалізація)",
            ]
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

            # Update visualization sheet
            await self.update_workout_program_visualization()

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

    async def update_workout_program_visualization(self) -> bool:
        """Update the visualization sheet with formatted workout programs.

        Creates a horizontal layout with 4 days per row section.

        Returns:
            True if successful, False otherwise
        """
        if not self.spreadsheet_id:
            return False

        try:
            # Get all programs first
            programs = await self.get_workout_programs(limit=500)
            if not programs:
                return True

            # Group exercises by day and muscle group
            # Structure: {day: {muscle_group: [exercises]}}
            days_data: dict[int, dict[str, list]] = {}
            for prog in programs:
                day = prog.get("day", 1)
                muscle = prog.get("muscle_group", "")
                if day not in days_data:
                    days_data[day] = {}
                if muscle not in days_data[day]:
                    days_data[day][muscle] = []
                days_data[day][muscle].append(prog)

            if not days_data:
                return True

            # Sort days
            sorted_days = sorted(days_data.keys())

            # Build visualization rows (4 days per section)
            all_rows = []
            days_per_row = 4

            for section_start in range(0, len(sorted_days), days_per_row):
                section_days = sorted_days[section_start:section_start + days_per_row]

                # Row 1: Day headers
                header_row = [""]
                for day in section_days:
                    header_row.append(f"📅 День {day}")
                all_rows.append(header_row)

                # Row 2: Muscle groups for each day
                muscle_row = [""]
                for day in section_days:
                    muscles = list(days_data[day].keys())
                    muscle_row.append(", ".join(muscles) if muscles else "")
                all_rows.append(muscle_row)

                # Find max exercises in this section
                max_exercises = 0
                for day in section_days:
                    for muscle, exercises in days_data[day].items():
                        max_exercises = max(max_exercises, len(exercises))

                # Exercise rows
                for ex_idx in range(max_exercises):
                    exercise_row = [f"{ex_idx + 1}"]
                    for day in section_days:
                        cell_content = []
                        for muscle, exercises in days_data[day].items():
                            if ex_idx < len(exercises):
                                ex = exercises[ex_idx]
                                name = ex.get("exercise", "")
                                sets = ex.get("sets", "")
                                reps = ex.get("reps", "")
                                cell_content.append(f"{name}\n{sets}x{reps}")
                        exercise_row.append("\n---\n".join(cell_content) if cell_content else "")
                    all_rows.append(exercise_row)

                # Empty row between sections
                all_rows.append([""])

            # Clear and update visualization sheet
            service = self._get_service()
            loop = asyncio.get_event_loop()

            # Clear existing data
            await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .clear(
                    spreadsheetId=self.spreadsheet_id,
                    range="Програми (Візуалізація)!A:Z",
                )
                .execute(),
            )

            # Write new data
            if all_rows:
                await loop.run_in_executor(
                    None,
                    lambda: service.spreadsheets()
                    .values()
                    .update(
                        spreadsheetId=self.spreadsheet_id,
                        range="Програми (Візуалізація)!A1",
                        valueInputOption="RAW",
                        body={"values": all_rows},
                    )
                    .execute(),
                )

            # Apply formatting
            await self._format_visualization_sheet(len(sorted_days), days_per_row)

            return True

        except HttpError as e:
            print(f"Google Sheets API error: {e}")
            return False
        except Exception as e:
            print(f"Error updating workout program visualization: {e}")
            return False

    async def _format_visualization_sheet(self, total_days: int, days_per_row: int) -> None:
        """Apply formatting to the visualization sheet."""
        if not self.spreadsheet_id:
            return

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            # Get sheet ID
            spreadsheet = await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .get(spreadsheetId=self.spreadsheet_id)
                .execute(),
            )

            sheet_id = None
            for sheet in spreadsheet.get("sheets", []):
                if sheet["properties"]["title"] == "Програми (Візуалізація)":
                    sheet_id = sheet["properties"]["sheetId"]
                    break

            if sheet_id is None:
                return

            requests = [
                # Set column widths
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": 1,
                        },
                        "properties": {"pixelSize": 40},
                        "fields": "pixelSize",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 1,
                            "endIndex": days_per_row + 1,
                        },
                        "properties": {"pixelSize": 200},
                        "fields": "pixelSize",
                    }
                },
                # Text wrapping for all cells
                {
                    "repeatCell": {
                        "range": {"sheetId": sheet_id},
                        "cell": {
                            "userEnteredFormat": {
                                "wrapStrategy": "WRAP",
                                "verticalAlignment": "TOP",
                            }
                        },
                        "fields": "userEnteredFormat.wrapStrategy,"
                        "userEnteredFormat.verticalAlignment",
                    }
                },
            ]

            await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"requests": requests},
                )
                .execute(),
            )

        except Exception as e:
            print(f"Error formatting visualization sheet: {e}")
