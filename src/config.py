"""Application configuration using pydantic-settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_int_list(value: str, default: list[int] | None = None) -> list[int]:
    """Parse comma-separated integers."""
    if not value or not value.strip():
        return default or []
    return [int(x.strip()) for x in value.split(",") if x.strip()]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str
    admin_user_ids_str: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./gym_bot.db"

    # Google API
    google_credentials_file: Path = Path("credentials.json")
    google_calendar_id: str = ""
    google_spreadsheet_id: str = ""

    # Timezone
    timezone: str = "Europe/Kyiv"

    # Notifications
    reminder_hours_before_str: str = "24,2"

    @computed_field
    @property
    def admin_user_ids(self) -> list[int]:
        """Get admin user IDs as list."""
        return _parse_int_list(self.admin_user_ids_str)

    @computed_field
    @property
    def reminder_hours_before(self) -> list[int]:
        """Get reminder hours as list."""
        return _parse_int_list(self.reminder_hours_before_str, [24, 2])


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
