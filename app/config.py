from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "JobScraper API"
    APP_ENV: str = "dev"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # IANA timezone the app reasons in for time windows. MUST match the DB
    # server's timezone: created_at is written by MySQL func.now() in the
    # server's local time (verified Europe/Berlin via NOW() vs UTC_TIMESTAMP()),
    # so window cutoffs compared against created_at must use the same frame.
    APP_TIMEZONE: str = "Europe/Berlin"

    DB_HOST: str = "db"
    DB_PORT: int = 3306
    DB_USER: str = "jobs"
    DB_PASSWORD: str = "jobs_pw"
    DB_NAME: str = "jobsdb"
    DB_POOL_SIZE: int = 10
    DB_POOL_MAX_OVERFLOW: int = 20

    # --- Description backfill (async /scrape background mode) -----------
    # Only LinkedIn jobs created within this window are eligible for
    # description backfill. Env-overridable; defaults to 3 days.
    DESCRIPTION_BACKFILL_WINDOW_DAYS: int = 3
    # Max rows fetched per backfill sweep (safety cap).
    DESCRIPTION_BACKFILL_LIMIT: int = 50
    # Max concurrent LinkedIn detail fetches in a sweep.
    DESCRIPTION_BACKFILL_CONCURRENCY: int = 2
    # Polite delay (seconds) before each LinkedIn detail fetch.
    DESCRIPTION_BACKFILL_DELAY_SECONDS: float = 2.0

    # --- country_indeed fallback --------------------------------------
    # jobspy requires country_indeed for Indeed/Glassdoor scrapes. Resolution
    # order at /scrape: request value > this env fallback > HTTP 400.
    # Leave unset to force callers to always pass country_indeed explicitly;
    # set it (e.g. "Germany") to make that the deployment-wide default.
    COUNTRY_INDEED_FALLBACK: Optional[str] = None

    # --- /jobs listing window -----------------------------------------
    # Default `created_after` for /jobs is now(UTC) minus this many days,
    # computed per request (rolling window) so it never freezes. Bounds
    # production while giving recently scraped-but-unapplied jobs a grace
    # window. Callers can pass created_after=null to disable the filter.
    CREATED_AFTER_WINDOW_DAYS: int = 7


    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
