import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


DB_PART_NAMES = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The database is given as the POSTGRES_* parts below (the same names the docker-compose files use; the
    # URL is built with the password percent-encoded, so "p@ss:w/rd" cannot break it). A full DATABASE_URL
    # still works as an override. When both appear, the PROCESS ENVIRONMENT beats the .env file, whichever
    # form each one uses - so a leftover line in .env can never silently redirect a run that sets its own
    # database (the test suite and throwaway smoke databases rely on that). See _resolve_database_url.
    database_url: str = ""
    postgres_host: str = ""
    postgres_port: int = 5432
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_db: str = ""

    jwt_secret: str
    jwt_expire_minutes: int = 60
    frontend_origin: str = "http://localhost:3000"
    cookie_secure: bool = False
    upload_dir: str = "uploads"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    # Operations (GĐ11): see app/core/rate_limit.py. 0 hops = never trust X-Forwarded-For.
    rate_limit_enabled: bool = True
    trusted_proxy_hops: int = 0

    @model_validator(mode="after")
    def _resolve_database_url(self) -> "Settings":
        env = {name.upper() for name in os.environ}
        env_has_url = "DATABASE_URL" in env
        env_has_parts = any(name in env for name in DB_PART_NAMES)
        # database_url may only have come from .env: ignore it when the environment names the database
        # through the POSTGRES_* parts instead (and the parts only count when they are complete).
        use_url = bool(self.database_url) and not (env_has_parts and not env_has_url)
        if use_url:
            return self
        if not (self.postgres_host and self.postgres_user and self.postgres_db):
            raise ValueError(
                "Set POSTGRES_HOST, POSTGRES_USER, POSTGRES_PASSWORD and POSTGRES_DB (or a full DATABASE_URL)"
            )
        self.database_url = URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
