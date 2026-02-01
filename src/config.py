"""Application configuration using pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_int_list(value: str, default: list[int] | None = None) -> list[int]:
    """Parse comma-separated integers."""
    if not value or not value.strip():
        return default or []
    return [int(x.strip()) for x in value.split(",") if x.strip()]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str
    admin_user_id: int = 0

    # Database - either use DATABASE_URL or build from components
    database_url: str | None = None
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "gym"
    postgres_password: str = "password"
    postgres_db: str = "gymdb"

    @property
    def db_url(self) -> str:
        """Get database URL - use DATABASE_URL if set, otherwise build from components."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Google API
    google_credentials_file_base64: str = ""
    google_calendar_id: str = ""
    google_spreadsheet_id: str = ""

    # Timezone
    timezone: str = "Europe/Kyiv"

    # Web App
    webapp_url: str = ""
    webapp_port: int = 8080

    # Notifications
    reminder_hours_before_str: str = "24,2"

    @property
    def admin_user_ids(self) -> list[int]:
        """Get admin user IDs as list."""
        if self.admin_user_id:
            return [self.admin_user_id]
        return []

    @property
    def reminder_hours_before(self) -> list[int]:
        """Get reminder hours as list."""
        return _parse_int_list(self.reminder_hours_before_str, [24, 2])


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
