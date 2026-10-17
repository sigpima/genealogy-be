from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Either a full DATABASE_URL, or the POSTGRES_* parts below (the URL is then built with the
    # password percent-encoded, so a password like "p@ss:w/rd" cannot break it). DATABASE_URL wins.
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

    @model_validator(mode="after")
    def _resolve_database_url(self) -> "Settings":
        if self.database_url:
            return self
        if not (self.postgres_host and self.postgres_user and self.postgres_db):
            raise ValueError(
                "Set DATABASE_URL, or POSTGRES_HOST, POSTGRES_USER, POSTGRES_PASSWORD and POSTGRES_DB"
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
