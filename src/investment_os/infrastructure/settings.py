"""Environment-backed bootstrap settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings with safe local defaults and no live-trading switch."""

    model_config = SettingsConfigDict(
        env_prefix="INVESTMENT_OS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = (
        "postgresql+asyncpg://investment_os:local-development-only@localhost:5432/investment_os"
    )
    worker_poll_seconds: float = Field(default=10.0, gt=0.0, le=300.0)
    worker_ready_file: Path = Path(".runtime/investment-os-worker-ready")
    worker_schedule_calendar_path: Path | None = None
    worker_scheduler_max_replay_sessions: int = Field(default=1, ge=1, le=31)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable-by-convention settings object per process."""

    return Settings()
