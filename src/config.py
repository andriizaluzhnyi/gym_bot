"""Application configuration using pydantic-settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str
    admin_user_ids: list[int] = []

    # Database
    database_url: str = "sqlite+aiosqlite:///./gym_bot.db"

    # Google API
    google_credentials_file: Path = Path("credentials.json")
    google_calendar_id: str = ""
    google_spreadsheet_id: str = ""

    # Timezone
    timezone: str = "Europe/Kyiv"

    # Notifications
    reminder_hours_before: list[int] = [24, 2]

    @field_validator("admin_user_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: str | list[int]) -> list[int]:
        """Parse comma-separated admin IDs."""
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    @field_validator("reminder_hours_before", mode="before")
    @classmethod
    def parse_reminder_hours(cls, v: str | list[int]) -> list[int]:
        """Parse comma-separated reminder hours."""
        if isinstance(v, str):
            if not v.strip():
                return [24, 2]
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
