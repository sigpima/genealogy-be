from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


def test_user_read_from_attributes():
    from app.schemas.user import UserRead

    class FakeUser:
        id = 1
        email = "a@example.com"
        full_name = "A B"
        role = "member"
        status = "pending"
        created_at = datetime.now(timezone.utc)

    read = UserRead.model_validate(FakeUser())
    assert read.id == 1
    assert read.email == "a@example.com"
    assert (read.role, read.status) == ("member", "pending")


def test_token_response_defaults_token_type_to_bearer():
    from app.schemas.auth import TokenResponse

    token = TokenResponse(access_token="abc123")
    assert token.token_type == "bearer"


def test_login_request_requires_email_and_password():
    from app.schemas.auth import LoginRequest

    with pytest.raises(ValidationError):
        LoginRequest(email="a@example.com")


def test_forgot_password_request_requires_valid_email():
    from app.schemas.auth import ForgotPasswordRequest

    with pytest.raises(ValidationError):
        ForgotPasswordRequest(email="not-an-email")


def test_reset_password_request_rejects_short_password():
    from app.schemas.auth import ResetPasswordRequest

    with pytest.raises(ValidationError):
        ResetPasswordRequest(token="abc", new_password="short")


def test_reset_password_request_accepts_valid_data():
    from app.schemas.auth import ResetPasswordRequest

    data = ResetPasswordRequest(token="abc", new_password="longenough")
    assert data.token == "abc"
