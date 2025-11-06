from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "JobScraper API"
    APP_ENV: str = "dev"
    APP_PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    DB_HOST: str = "db"
    DB_PORT: int = 3306
    DB_USER: str = "jobs"
    DB_PASSWORD: str = "jobs_pw"
    DB_NAME: str = "jobsdb"
    DB_POOL_SIZE: int = 10
    DB_POOL_MAX_OVERFLOW: int = 20


    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
