import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", "60")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_hash_password_roundtrip():
    from app.core.security import hash_password, verify_password

    hashed = hash_password("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert verify_password("s3cret-pass", hashed) is True


def test_verify_password_rejects_wrong_password():
    from app.core.security import hash_password, verify_password

    hashed = hash_password("s3cret-pass")
    assert verify_password("wrong-pass", hashed) is False


def test_create_and_decode_access_token_roundtrip():
    from app.core.security import create_access_token, decode_access_token

    token = create_access_token(subject="user@example.com")
    assert decode_access_token(token) == "user@example.com"


def test_decode_access_token_rejects_expired_token():
    from app.core.security import InvalidTokenError, create_access_token, decode_access_token

    token = create_access_token(subject="user@example.com", expires_minutes=-1)
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)


def test_decode_access_token_rejects_garbage_token():
    from app.core.security import InvalidTokenError, decode_access_token

    with pytest.raises(InvalidTokenError):
        decode_access_token("not-a-real-token")
