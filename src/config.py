"""Application configuration using pydantic-settings."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_int_list(v: str | list[int] | None) -> list[int]:
    """Parse comma-separated integers or return list as-is."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return []
        return [int(x.strip()) for x in v.split(",") if x.strip()]
    return []


IntList = Annotated[list[int], BeforeValidator(parse_int_list)]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str
    admin_user_ids: IntList = []

    # Database
    database_url: str = "sqlite+aiosqlite:///./gym_bot.db"

    # Google API
    google_credentials_file: Path = Path("credentials.json")
    google_calendar_id: str = ""
    google_spreadsheet_id: str = ""

    # Timezone
    timezone: str = "Europe/Kyiv"

    # Notifications
    reminder_hours_before: IntList = [24, 2]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
