from datetime import datetime, timedelta, timezone

from sqlalchemy import select


async def test_create_password_reset_token(session):
    from app.models.password_reset_token import PasswordResetToken
    from app.models.user import User

    user = User(email="a@example.com", hashed_password="hashed", full_name="A B")
    session.add(user)
    await session.commit()
    await session.refresh(user)

    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=30)
    token = PasswordResetToken(user_id=user.id, token_hash="a" * 64, expires_at=expires_at)
    session.add(token)
    await session.commit()

    result = await session.execute(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )
    fetched = result.scalar_one()
    assert fetched.token_hash == "a" * 64
    assert fetched.used_at is None
    assert fetched.created_at is not None
