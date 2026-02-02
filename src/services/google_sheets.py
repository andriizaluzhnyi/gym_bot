"""Google Sheets integration service."""

import asyncio
import base64
import json
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
        self.credentials_base64 = settings.google_credentials_file_base64
        self._service = None

    def _get_service(self):
        """Get or create Google Sheets service."""
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
        }

        headers["Програми"] = [
            ["День", "Група м'язів", "Вправа", "Підходи/Повторення", "Коментар", "Дата"]
        ]

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

    async def _ensure_user_sheets_exist(self, user_name: str) -> None:
        """Ensure sheets for a specific user exist.

        Creates two sheets per user:
        - 'Програми ({user_name})' - hidden data sheet
        - '{user_name}' - visible visualization sheet

        Args:
            user_name: The username to create sheets for
        """
        if not self.spreadsheet_id or not user_name:
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

            data_sheet = f"Програми ({user_name})"
            viz_sheet = user_name

            sheets_to_create = []
            if data_sheet not in existing_sheets:
                sheets_to_create.append(data_sheet)
            if viz_sheet not in existing_sheets:
                sheets_to_create.append(viz_sheet)

            if not sheets_to_create:
                return

            # Create sheets
            requests = [
                {"addSheet": {"properties": {"title": title}}}
                for title in sheets_to_create
            ]

            await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .batchUpdate(spreadsheetId=self.spreadsheet_id, body={"requests": requests})
                .execute(),
            )

            # Add headers to data sheet
            if data_sheet in sheets_to_create:
                await loop.run_in_executor(
                    None,
                    lambda: service.spreadsheets()
                    .values()
                    .update(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"{data_sheet}!A1",
                        valueInputOption="RAW",
                        body={
                            "values": [
                                ["День", "Група м'язів", "Вправа", "Підходи/Повторення", "Коментар", "Дата"]
                            ]
                        },
                    )
                    .execute(),
                )

            # Hide data sheet
            await self._hide_sheet(data_sheet)

        except Exception as e:
            print(f"Error ensuring user sheets exist: {e}")

    async def _hide_sheet(self, sheet_name: str) -> None:
        """Hide a specific sheet by name.

        Args:
            sheet_name: Name of the sheet to hide
        """
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
                if sheet["properties"]["title"] == sheet_name:
                    sheet_id = sheet["properties"]["sheetId"]
                    break

            if sheet_id is None:
                return

            await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "updateSheetProperties": {
                                    "properties": {
                                        "sheetId": sheet_id,
                                        "hidden": True,
                                    },
                                    "fields": "hidden",
                                }
                            }
                        ]
                    },
                )
                .execute(),
            )

        except Exception as e:
            print(f"Error hiding sheet {sheet_name}: {e}")

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

    async def add_workout_program(
        self, exercises: list[dict], user_name: str | None = None
    ) -> bool:
        """Add workout program exercises to the Programs sheet.

        Args:
            exercises: List of exercise dictionaries with 'day' field
            user_name: Optional user name for per-user sheets

        Returns:
            True if successful, False otherwise
        """
        if not self.spreadsheet_id:
            return False

        try:
            await self._ensure_sheets_exist()

            # Ensure user-specific sheets exist if user_name provided
            if user_name:
                await self._ensure_user_sheets_exist(user_name)

            service = self._get_service()
            loop = asyncio.get_event_loop()

            rows = []
            for ex in exercises:
                row = [
                    str(ex.get("day", 1)),
                    ex.get("muscle_group", ""),
                    ex.get("exercise", ""),
                    ex.get("sets_reps", ""),
                    ex.get("comment", ""),
                    ex.get("created_at", datetime.now().strftime("%d.%m.%Y %H:%M")),
                ]
                rows.append(row)

            # Determine sheet name based on user
            if user_name:
                sheet_name = f"Програми ({user_name})"
            else:
                sheet_name = "Програми"

            await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{sheet_name}!A:F",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": rows},
                )
                .execute(),
            )

            # Update visualization sheet for this user
            await self.update_workout_program_visualization(user_name)

            return True

        except HttpError as e:
            print(f"Google Sheets API error: {e}")
            return False
        except Exception as e:
            print(f"Error adding workout program: {e}")
            return False

    async def delete_workout_day(
        self, user_name: str, day: str
    ) -> bool:
        """Delete all exercises for a specific day from workout program.

        Args:
            user_name: User name
            day: Day number to delete

        Returns:
            True if successful, False otherwise
        """
        if not self.spreadsheet_id:
            return False

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            sheet_name = f"Програми ({user_name})"

            # Get all data
            result = await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range=f"{sheet_name}!A:F")
                .execute(),
            )

            values = result.get("values", [])
            if len(values) <= 1:
                return False

            # Find rows to delete (keep header)
            new_values = [values[0]]  # Header
            for row in values[1:]:
                if len(row) > 0 and row[0] != day:
                    new_values.append(row)

            # Clear sheet and write filtered data
            await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .clear(spreadsheetId=self.spreadsheet_id, range=f"{sheet_name}!A2:F")
                .execute(),
            )

            if len(new_values) > 1:
                await loop.run_in_executor(
                    None,
                    lambda: service.spreadsheets()
                    .values()
                    .update(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"{sheet_name}!A2",
                        valueInputOption="RAW",
                        body={"values": new_values[1:]},
                    )
                    .execute(),
                )

            return True

        except Exception as e:
            print(f"Error deleting workout day: {e}")
            return False

    async def delete_exercise(
        self, user_name: str, day: str, exercise: str
    ) -> bool:
        """Delete a specific exercise from workout program.

        Args:
            user_name: User name
            day: Day number
            exercise: Exercise name to delete

        Returns:
            True if successful, False otherwise
        """
        if not self.spreadsheet_id:
            return False

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            sheet_name = f"Програми ({user_name})"

            # Get all data
            result = await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range=f"{sheet_name}!A:F")
                .execute(),
            )

            values = result.get("values", [])
            if len(values) <= 1:
                return False

            # Find row to delete (keep header)
            new_values = [values[0]]  # Header
            deleted = False
            for row in values[1:]:
                # Skip row if it matches day and exercise
                if len(row) > 2 and row[0] == day and row[2] == exercise:
                    deleted = True
                    continue
                new_values.append(row)

            if not deleted:
                return False

            # Clear sheet and write filtered data
            await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .clear(spreadsheetId=self.spreadsheet_id, range=f"{sheet_name}!A2:F")
                .execute(),
            )

            if len(new_values) > 1:
                await loop.run_in_executor(
                    None,
                    lambda: service.spreadsheets()
                    .values()
                    .update(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"{sheet_name}!A2",
                        valueInputOption="RAW",
                        body={"values": new_values[1:]},
                    )
                    .execute(),
                )

            return True

        except Exception as e:
            print(f"Error deleting exercise: {e}")
            return False

    async def get_workout_programs(
        self, limit: int = 50, user_name: str | None = None
    ) -> list[dict]:
        """Get workout programs from the Programs sheet.

        Args:
            limit: Maximum number of records to return
            user_name: Optional user name for per-user sheets

        Returns:
            List of program dictionaries
        """
        if not self.spreadsheet_id:
            return []

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            # Determine sheet name based on user
            if user_name:
                sheet_name = f"Програми ({user_name})"
            else:
                sheet_name = "Програми"

            result = await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range=f"{sheet_name}!A:F")
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
                        "sets_reps": row[3] if len(row) > 3 else "",
                        "comment": row[4] if len(row) > 4 else "",
                        "created_at": row[5] if len(row) > 5 else "",
                    })

            return programs[-limit:] if limit else programs

        except HttpError as e:
            print(f"Google Sheets API error: {e}")
            return []
        except Exception as e:
            print(f"Error getting workout programs: {e}")
            return []

    async def get_last_program_day(self, user_name: str | None = None) -> int:
        """Get the last day number from Programs sheet.

        Args:
            user_name: Optional user name for per-user sheets

        Returns:
            Last day number or 0 if no programs exist
        """
        if not self.spreadsheet_id:
            return 0

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            # Determine sheet name based on user
            if user_name:
                sheet_name = f"Програми ({user_name})"
            else:
                sheet_name = "Програми"

            result = await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range=f"{sheet_name}!A:A")
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

    async def get_last_program_day_for_muscle_group(
        self, muscle_group: str, user_name: str | None = None
    ) -> int:
        """Get the last day number for a specific muscle group.

        Args:
            muscle_group: The muscle group to filter by
            user_name: Optional user name for per-user sheets

        Returns:
            Last day number for this muscle group or 0 if none exist
        """
        if not self.spreadsheet_id:
            return 0

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            # Determine sheet name based on user
            if user_name:
                sheet_name = f"Програми ({user_name})"
            else:
                sheet_name = "Програми"

            # Get columns A (Day) and B (Muscle Group)
            result = await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range=f"{sheet_name}!A:B")
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

    async def update_workout_program_visualization(
        self, user_name: str | None = None
    ) -> bool:
        """Update the visualization sheet with formatted workout programs.

        Creates a layout grouped by muscle groups with days as columns.

        Args:
            user_name: Optional user name for per-user sheets

        Returns:
            True if successful, False otherwise
        """
        if not self.spreadsheet_id:
            return False

        try:
            # Get all programs first for this user
            programs = await self.get_workout_programs(limit=500, user_name=user_name)
            if not programs:
                return True

            # Group exercises by muscle group and day
            # Structure: {muscle_group: {day: [exercises]}}
            muscle_data: dict[str, dict[int, list]] = {}
            all_days: set[int] = set()

            for prog in programs:
                day = prog.get("day", 1)
                muscle = prog.get("muscle_group", "")
                all_days.add(day)
                if muscle not in muscle_data:
                    muscle_data[muscle] = {}
                if day not in muscle_data[muscle]:
                    muscle_data[muscle][day] = []
                muscle_data[muscle][day].append(prog)

            if not muscle_data:
                return True

            # Sort days
            sorted_days = sorted(all_days)
            num_days = len(sorted_days)

            # Build visualization rows
            all_rows = []

            # Header row: empty | День 1 | Підходи/Повт | День 2 | Підходи/Повт | ...
            header_row = [""]
            for day in sorted_days:
                header_row.append(f"День {day}")
                header_row.append("Підходи/Повторення")
            all_rows.append(header_row)

            # For each muscle group, create a section
            for muscle_group in muscle_data.keys():
                # Muscle group header row (will be merged later)
                muscle_header = [muscle_group] + [""] * (num_days * 2)
                all_rows.append(muscle_header)

                # Find max exercises for this muscle group across all days
                max_exercises = 0
                for day in sorted_days:
                    exercises = muscle_data[muscle_group].get(day, [])
                    max_exercises = max(max_exercises, len(exercises))

                # Exercise rows
                for ex_idx in range(max_exercises):
                    exercise_row = [""]
                    for day in sorted_days:
                        exercises = muscle_data[muscle_group].get(day, [])
                        if ex_idx < len(exercises):
                            ex = exercises[ex_idx]
                            name = ex.get("exercise", "")
                            sets_reps = ex.get("sets_reps", "")
                            exercise_row.append(name)
                            exercise_row.append(sets_reps)
                        else:
                            exercise_row.append("")
                            exercise_row.append("")
                    all_rows.append(exercise_row)

            # Determine visualization sheet name based on user
            if user_name:
                viz_sheet_name = user_name
            else:
                viz_sheet_name = "Програми (Візуалізація)"

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
                    range=f"{viz_sheet_name}!A:Z",
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
                        range=f"{viz_sheet_name}!A1",
                        valueInputOption="RAW",
                        body={"values": all_rows},
                    )
                    .execute(),
                )

            # Apply formatting
            await self._format_visualization_sheet(
                num_days, all_rows, muscle_data, user_name
            )

            return True

        except HttpError as e:
            print(f"Google Sheets API error: {e}")
            return False
        except Exception as e:
            print(f"Error updating workout program visualization: {e}")
            return False

    async def _format_visualization_sheet(
        self,
        num_days: int,
        all_rows: list,
        muscle_data: dict,
        user_name: str | None = None,
    ) -> None:
        """Apply formatting to the visualization sheet."""
        if not self.spreadsheet_id:
            return

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            # Determine visualization sheet name based on user
            if user_name:
                viz_sheet_name = user_name
            else:
                viz_sheet_name = "Програми (Візуалізація)"

            # Get sheet ID
            spreadsheet = await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .get(spreadsheetId=self.spreadsheet_id)
                .execute(),
            )

            sheet_id = None
            for sheet in spreadsheet.get("sheets", []):
                if sheet["properties"]["title"] == viz_sheet_name:
                    sheet_id = sheet["properties"]["sheetId"]
                    break

            if sheet_id is None:
                return

            total_cols = num_days * 2 + 1  # +1 for first column

            requests = [
                # Set first column width (narrow)
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": 1,
                        },
                        "properties": {"pixelSize": 50},
                        "fields": "pixelSize",
                    }
                },
                # Set exercise name columns width
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 1,
                            "endIndex": total_cols,
                        },
                        "properties": {"pixelSize": 180},
                        "fields": "pixelSize",
                    }
                },
                # Text wrapping and alignment for all cells
                {
                    "repeatCell": {
                        "range": {"sheetId": sheet_id},
                        "cell": {
                            "userEnteredFormat": {
                                "wrapStrategy": "WRAP",
                                "verticalAlignment": "MIDDLE",
                            }
                        },
                        "fields": "userEnteredFormat.wrapStrategy,"
                        "userEnteredFormat.verticalAlignment",
                    }
                },
                # Header row formatting (bold, background)
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "backgroundColor": {
                                    "red": 0.9,
                                    "green": 0.9,
                                    "blue": 0.9,
                                },
                                "horizontalAlignment": "CENTER",
                            }
                        },
                        "fields": "userEnteredFormat.textFormat.bold,"
                        "userEnteredFormat.backgroundColor,"
                        "userEnteredFormat.horizontalAlignment",
                    }
                },
            ]

            # Find muscle group header rows and format them
            current_row = 1  # Start after header
            for muscle_group in muscle_data.keys():
                # Merge muscle group header cells
                requests.append({
                    "mergeCells": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": current_row,
                            "endRowIndex": current_row + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": total_cols,
                        },
                        "mergeType": "MERGE_ALL",
                    }
                })
                # Format muscle group header (bold, centered, background)
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": current_row,
                            "endRowIndex": current_row + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True},
                                "backgroundColor": {
                                    "red": 1.0,
                                    "green": 0.95,
                                    "blue": 0.8,
                                },
                                "horizontalAlignment": "CENTER",
                            }
                        },
                        "fields": "userEnteredFormat.textFormat.bold,"
                        "userEnteredFormat.backgroundColor,"
                        "userEnteredFormat.horizontalAlignment",
                    }
                })

                # Calculate exercises count for this muscle group
                max_exercises = 0
                for day_exercises in muscle_data[muscle_group].values():
                    max_exercises = max(max_exercises, len(day_exercises))

                current_row += 1 + max_exercises  # header + exercises

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

    async def _ensure_workout_log_sheet_exists(self, user_name: str) -> None:
        """Ensure workout log sheet exists for a specific user.

        Creates sheet 'Логи ({user_name})' with appropriate headers
        if it does not already exist.

        Args:
            user_name: Username to create log sheet for
        """
        if not self.spreadsheet_id or not user_name:
            return

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            spreadsheet = await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .get(spreadsheetId=self.spreadsheet_id)
                .execute(),
            )

            existing_sheets = {
                sheet["properties"]["title"]
                for sheet in spreadsheet.get("sheets", [])
            }

            log_sheet = f"Логи ({user_name})"

            if log_sheet in existing_sheets:
                return

            await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={
                        "requests": [
                            {"addSheet": {"properties": {"title": log_sheet}}}
                        ]
                    },
                )
                .execute(),
            )

            await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{log_sheet}!A1",
                    valueInputOption="RAW",
                    body={
                        "values": [
                            [
                                "Дата",
                                "Вправа",
                                "Група м'язів",
                                "День",
                                "Сет",
                                "Вага",
                                "Повторення",
                                "Плановані Підходи/Повторення",
                                "Час",
                            ]
                        ]
                    },
                )
                .execute(),
            )

        except Exception as e:
            print(f"Error ensuring workout log sheet exists: {e}")

    async def save_workout_log(
        self, user_name: str, log_entries: list[dict]
    ) -> bool:
        """Save workout log entries to the user's log sheet.

        Each entry represents one set of one exercise.

        Args:
            user_name: Username whose log sheet to write to
            log_entries: List of dicts with keys: date, exercise,
                muscle_group, day, set_number, weight, reps,
                planned_sets_reps, timestamp

        Returns:
            True if successful, False otherwise
        """
        if not self.spreadsheet_id or not user_name:
            return False

        try:
            await self._ensure_workout_log_sheet_exists(user_name)

            service = self._get_service()
            loop = asyncio.get_event_loop()

            rows = []
            for entry in log_entries:
                rows.append([
                    entry.get("date", ""),
                    entry.get("exercise", ""),
                    entry.get("muscle_group", ""),
                    str(entry.get("day", "")),
                    str(entry.get("set_number", "")),
                    str(entry.get("weight", "")),
                    str(entry.get("reps", "")),
                    entry.get("planned_sets_reps", ""),
                    entry.get("timestamp", ""),
                ])

            log_sheet = f"Логи ({user_name})"

            await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{log_sheet}!A:I",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": rows},
                )
                .execute(),
            )

            return True

        except HttpError as e:
            print(f"Google Sheets API error saving workout log: {e}")
            return False
        except Exception as e:
            print(f"Error saving workout log: {e}")
            return False

    async def get_last_workout_log(
        self, user_name: str, exercises: list[str], day: int | None = None
    ) -> dict[str, dict]:
        """Get the most recent workout log data for given exercises.

        Reads the entire log sheet once and filters in memory to avoid
        multiple API calls.

        Args:
            user_name: Username whose log sheet to read
            exercises: List of exercise names to look up
            day: Optional day number to filter by (e.g., 1 for "День 1")

        Returns:
            Dict mapping exercise name to its last log data:
            {
                "Exercise Name": {
                    "date": "05.01.2026",
                    "sets": [
                        {"set": 1, "weight": 50, "reps": 20},
                        {"set": 2, "weight": 70, "reps": 12},
                    ]
                }
            }
        """
        if not self.spreadsheet_id or not user_name:
            return {}

        try:
            service = self._get_service()
            loop = asyncio.get_event_loop()

            log_sheet = f"Логи ({user_name})"

            result = await loop.run_in_executor(
                None,
                lambda: service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{log_sheet}!A:I",
                )
                .execute(),
            )

            values = result.get("values", [])

            if len(values) <= 1:
                return {}

            exercises_set = set(exercises)
            # Group by exercise -> date -> sets
            exercise_dates: dict[str, dict[str, list]] = {}

            for row in values[1:]:
                if len(row) < 7:
                    continue

                date = row[0]
                exercise = row[1]
                log_day = row[3] if len(row) > 3 else None

                if exercise not in exercises_set:
                    continue

                # Filter by day if specified
                if day is not None:
                    if not log_day or str(log_day).strip() != str(day):
                        continue

                set_number = row[4]
                weight = row[5]
                reps = row[6]

                # Skip sets with empty weight or reps (incomplete sets)
                if not weight or not reps:
                    continue

                if exercise not in exercise_dates:
                    exercise_dates[exercise] = {}
                if date not in exercise_dates[exercise]:
                    exercise_dates[exercise][date] = []

                try:
                    exercise_dates[exercise][date].append({
                        "set": int(set_number),
                        "weight": float(weight),
                        "reps": int(reps),
                    })
                except (ValueError, TypeError):
                    continue

            # For each exercise, find the most recent date
            output: dict[str, dict] = {}
            for exercise_name, dates_data in exercise_dates.items():
                if not dates_data:
                    continue

                # Sort dates (format DD.MM.YYYY) to find the latest
                sorted_dates = sorted(
                    dates_data.keys(),
                    key=lambda d: datetime.strptime(d, "%d.%m.%Y")
                    if d
                    else datetime.min,
                    reverse=True,
                )

                latest_date = sorted_dates[0]
                sets = sorted(
                    dates_data[latest_date], key=lambda s: s["set"]
                )

                output[exercise_name] = {
                    "date": latest_date,
                    "sets": sets,
                }

            return output

        except HttpError:
            return {}
        except Exception as e:
            print(f"Error getting last workout log: {e}")
            return {}
