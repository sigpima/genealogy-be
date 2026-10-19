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


# ---- golden masters: credentials made by the previous libraries (passlib + python-jose) must keep working after the swap
OLD_HASH = "$2b$12$Bz1O6BetBYs4RS6HB4PkK.7wbdvhL4OZl0DZRpktLNXkp/.dO.kJ2"  # passlib hash of "mật-khẩu-cũ-1"
OLD_LONG_HASH = "$2b$12$uHC42AiC/kKx5hEfTzUyP.YzTpjR1NGmRzk9dBlqPl01CYLdjNSZ6"  # passlib hash of "x" * 100
OLD_TOKEN = (  # python-jose HS256 token for old@example.com, valid until 2099, secret "test-secret"
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJvbGRAZXhhbXBsZS5jb20iLCJleHAiOjQwNzA5MDg4MDB9."
    "HZcnVz8kH6ass-H7tyinc_kG3UfeauqBDOkPT6l266o"
)
OLD_EXPIRED_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJvbGRAZXhhbXBsZS5jb20iLCJleHAiOjE1Nzc4MzY4MDB9."
    "Cjby0LEWVh6luquOehIXO2hz_LChvJs-OO5-ZRhVPjM"
)


def test_a_password_hash_made_by_the_old_library_still_verifies():
    from app.core.security import verify_password

    assert verify_password("mật-khẩu-cũ-1", OLD_HASH) is True
    assert verify_password("mật-khẩu-cũ-2", OLD_HASH) is False


def test_bcrypt_only_reads_72_bytes_and_longer_passwords_neither_crash_nor_differ_in_the_tail():
    from app.core.security import hash_password, verify_password

    assert verify_password("x" * 100, OLD_LONG_HASH) is True  # old hashes of long passwords still open
    assert verify_password("x" * 72, OLD_LONG_HASH) is True  # ... because only the first 72 bytes ever counted
    hashed = hash_password("y" * 200)
    assert verify_password("y" * 200, hashed) is True
    assert verify_password("z" * 200, hashed) is False


def test_a_new_hash_is_bcrypt_2b_with_a_salt():
    from app.core.security import hash_password

    first, second = hash_password("same-password-1"), hash_password("same-password-1")
    assert first.startswith("$2b$") and first != second


def test_a_garbage_hash_is_a_failed_login_not_a_crash():
    from app.core.security import verify_password

    assert verify_password("anything", "not-a-hash") is False
    assert verify_password("anything", "") is False


def test_a_token_issued_by_the_old_library_still_works_so_nobody_is_logged_out_by_the_upgrade():
    from app.core.security import InvalidTokenError, decode_access_token

    assert decode_access_token(OLD_TOKEN) == "old@example.com"
    with pytest.raises(InvalidTokenError):
        decode_access_token(OLD_EXPIRED_TOKEN)


def test_a_token_signed_with_another_secret_or_without_a_signature_is_refused():
    import base64
    import json

    from app.core.security import InvalidTokenError, decode_access_token

    other = OLD_TOKEN[:-5] + ("AAAAA" if not OLD_TOKEN.endswith("AAAAA") else "BBBBB")  # a damaged signature
    with pytest.raises(InvalidTokenError):
        decode_access_token(other)
    b64 = lambda data: base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()  # noqa: E731
    unsigned = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': 'root@example.com', 'exp': 4070908800})}."
    with pytest.raises(InvalidTokenError):
        decode_access_token(unsigned)  # "alg: none" must never be accepted


def test_a_token_that_names_nobody_is_refused():
    import jwt

    from app.core.security import InvalidTokenError, decode_access_token

    token = jwt.encode({"exp": 4070908800}, "test-secret", algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token)
