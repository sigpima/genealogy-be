from app.core.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "30")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+asyncpg://u:p@localhost/db"
    assert settings.jwt_secret == "test-secret"
    assert settings.jwt_expire_minutes == 30


def test_settings_jwt_expire_minutes_defaults_to_60(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("JWT_EXPIRE_MINUTES", raising=False)

    settings = Settings(_env_file=None)

    assert settings.jwt_expire_minutes == 60


def test_settings_defaults_for_frontend_origin_and_cookie_secure(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("FRONTEND_ORIGIN", raising=False)
    monkeypatch.delenv("COOKIE_SECURE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.frontend_origin == "http://localhost:3000"
    assert settings.cookie_secure is False


def test_settings_reads_frontend_origin_and_cookie_secure_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://example.com")
    monkeypatch.setenv("COOKIE_SECURE", "true")

    settings = Settings(_env_file=None)

    assert settings.frontend_origin == "https://example.com"
    assert settings.cookie_secure is True


def test_settings_upload_dir_defaults_to_uploads(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("UPLOAD_DIR", raising=False)

    settings = Settings(_env_file=None)

    assert settings.upload_dir == "uploads"


def test_settings_reads_upload_dir_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("UPLOAD_DIR", "/tmp/custom-uploads")

    settings = Settings(_env_file=None)

    assert settings.upload_dir == "/tmp/custom-uploads"


def test_settings_smtp_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    for var in ("SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_USE_TLS"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)

    assert settings.smtp_host == ""
    assert settings.smtp_port == 587
    assert settings.smtp_use_tls is True


def test_settings_reads_smtp_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USERNAME", "bot@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "no-reply@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "false")

    settings = Settings(_env_file=None)

    assert settings.smtp_host == "smtp.example.com"
    assert settings.smtp_port == 2525
    assert settings.smtp_username == "bot@example.com"
    assert settings.smtp_password == "secret"
    assert settings.smtp_from == "no-reply@example.com"
    assert settings.smtp_use_tls is False


def _clear_db_env(monkeypatch):
    for var in ("DATABASE_URL", "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("JWT_SECRET", "test-secret")


def test_settings_builds_database_url_from_postgres_parts(monkeypatch):
    from sqlalchemy.engine import make_url

    _clear_db_env(monkeypatch)
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_USER", "genealogy")
    monkeypatch.setenv("POSTGRES_PASSWORD", "plain")
    monkeypatch.setenv("POSTGRES_DB", "genealogy")

    settings = Settings(_env_file=None)

    url = make_url(settings.database_url)
    assert url.drivername == "postgresql+asyncpg"
    assert (url.host, url.port, url.username, url.password, url.database) == (
        "db", 5432, "genealogy", "plain", "genealogy",
    )


def test_postgres_password_with_url_special_characters_round_trips(monkeypatch):
    """A password like 'p@ss:w/rd#?%x' must not be parsed as part of the host."""
    from sqlalchemy.engine import make_url

    password = "p@ss:w/rd#?%x&=+ ü"
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_USER", "genealogy")
    monkeypatch.setenv("POSTGRES_PASSWORD", password)
    monkeypatch.setenv("POSTGRES_DB", "genealogy")

    settings = Settings(_env_file=None)

    for url_text in (settings.database_url, settings.database_url.replace("+asyncpg", "+psycopg2")):
        url = make_url(url_text)
        assert url.password == password
        assert url.host == "db"
        assert url.database == "genealogy"


def test_database_url_wins_over_postgres_parts(monkeypatch):
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@elsewhere/other")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_USER", "genealogy")
    monkeypatch.setenv("POSTGRES_PASSWORD", "plain")
    monkeypatch.setenv("POSTGRES_DB", "genealogy")

    assert Settings(_env_file=None).database_url == "postgresql+asyncpg://u:p@elsewhere/other"


def test_missing_database_settings_is_a_clear_error(monkeypatch):
    import pytest
    from pydantic import ValidationError

    _clear_db_env(monkeypatch)
    monkeypatch.setenv("POSTGRES_HOST", "db")  # user/password/db missing

    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=None)


# --- precedence: the process environment beats the .env file, whichever form each one uses ----------


def _dotenv(tmp_path, *lines):
    path = tmp_path / ".env"
    path.write_text("\n".join(lines) + "\n")
    return path


PARTS_IN_FILE = (
    "POSTGRES_HOST=127.0.0.1",
    "POSTGRES_PORT=15432",
    "POSTGRES_USER=postgres",
    "POSTGRES_PASSWORD=from-file",
    "POSTGRES_DB=genealogy",
)


def test_dotenv_alone_can_use_the_postgres_parts(monkeypatch, tmp_path):
    from sqlalchemy.engine import make_url

    _clear_db_env(monkeypatch)
    url = make_url(Settings(_env_file=_dotenv(tmp_path, *PARTS_IN_FILE)).database_url)

    assert (url.host, url.port, url.database) == ("127.0.0.1", 15432, "genealogy")


def test_dotenv_alone_can_still_use_a_full_database_url(monkeypatch, tmp_path):
    _clear_db_env(monkeypatch)
    env_file = _dotenv(tmp_path, "DATABASE_URL=postgresql+asyncpg://u:p@filehost/filedb")

    assert Settings(_env_file=env_file).database_url == "postgresql+asyncpg://u:p@filehost/filedb"


def test_env_postgres_parts_beat_a_database_url_in_dotenv(monkeypatch, tmp_path):
    """The mix-up this guards against: a throwaway database set via POSTGRES_* silently ignored because a
    leftover DATABASE_URL in .env pointed somewhere else."""
    from sqlalchemy.engine import make_url

    _clear_db_env(monkeypatch)
    for name, value in (("HOST", "db"), ("USER", "genealogy"), ("PASSWORD", "x"), ("DB", "fresh")):
        monkeypatch.setenv(f"POSTGRES_{name}", value)
    env_file = _dotenv(tmp_path, "DATABASE_URL=postgresql+asyncpg://u:p@filehost/filedb")

    url = make_url(Settings(_env_file=env_file).database_url)

    assert (url.host, url.database) == ("db", "fresh")


def test_env_database_url_beats_postgres_parts_in_dotenv(monkeypatch, tmp_path):
    """The test suite relies on this: its DATABASE_URL must win over a developer's .env."""
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@envhost/envdb")

    assert Settings(_env_file=_dotenv(tmp_path, *PARTS_IN_FILE)).database_url == "postgresql+asyncpg://u:p@envhost/envdb"


def test_the_error_names_the_postgres_variables_first(monkeypatch):
    import pytest
    from pydantic import ValidationError

    _clear_db_env(monkeypatch)

    with pytest.raises(ValidationError, match="POSTGRES_HOST"):
        Settings(_env_file=None)
