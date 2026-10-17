import asyncio
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.email import send_password_reset_email
from app.core.roles import (
    ROLE_MEMBER,
    ROLE_SUPERADMIN,
    STATUS_ACTIVE,
    STATUS_DISABLED,
    STATUS_PENDING,
    get_tree_settings,
)
from app.core.tenancy import public_tree
from app.core.tenants import get_or_create_default_tree
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models.password_reset_token import PasswordResetToken
from app.models.tree import Tree
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

ACCESS_TOKEN_COOKIE = "access_token"
RESET_TOKEN_EXPIRE_MINUTES = 30


def _utcnow() -> datetime:
    # Naive UTC on purpose - see genealogy-api/CLAUDE.md: SQLite silently
    # drops tzinfo on round-trip for DateTime(timezone=True), which would
    # break expiry comparisons in tests but not in real Postgres.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_token_from_request(request: Request) -> str:
    cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if cookie_token:
        return cookie_token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:]
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserCreate, request: Request, db: AsyncSession = Depends(get_db)
) -> UserRead:
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        )

    # A fresh install must be usable: while there are no users at all, the first registration
    # becomes the (tree-less) superadmin and a default tree is created if there is none yet.
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    tree: Tree | None = None
    if user_count == 0:
        await get_or_create_default_tree(db)
        role, account_status = ROLE_SUPERADMIN, STATUS_ACTIVE
    else:
        # Everybody else joins the tree they refer to (cookie, or the only tree), under THAT tree's rules.
        tree = await public_tree(request, db, ambiguous_status=status.HTTP_400_BAD_REQUEST)
        mode = (await get_tree_settings(db, tree.id))["registration"]
        if mode == "closed":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="registration is closed"
            )
        role = ROLE_MEMBER
        account_status = STATUS_ACTIVE if mode == "open" else STATUS_PENDING

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=role,
        status=account_status,
        tree_id=tree.id if tree else None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    read = UserRead.model_validate(user)
    read.tree_name = tree.name if tree else None
    return read


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )
    if user.status == STATUS_PENDING:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_pending")
    if user.status == STATUS_DISABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_disabled")

    token = create_access_token(subject=user.email)
    settings = get_settings()
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.jwt_expire_minutes * 60,
        path="/",
    )
    return TokenResponse(access_token=token)


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(ACCESS_TOKEN_COOKIE, path="/")
    return {"detail": "logged out"}


async def get_current_user(
    token: str = Depends(get_token_from_request), db: AsyncSession = Depends(get_db)
) -> User:
    try:
        email = decode_access_token(token)
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token"
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    # Checked on every request (not just at login) so disabling an account takes effect at once.
    if user.status != STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"account_{user.status}")
    return user


@router.get("/me", response_model=UserRead)
async def read_current_user(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> UserRead:
    read = UserRead.model_validate(current_user)
    if current_user.tree_id is not None:
        tree = await db.get(Tree, current_user.tree_id)
        read.tree_name = tree.name if tree else None
    return read


@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is not None:
        raw_token = secrets.token_urlsafe(32)
        reset_token = PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_reset_token(raw_token),
            expires_at=_utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
        )
        db.add(reset_token)
        await db.commit()

        settings = get_settings()
        reset_url = f"{settings.frontend_origin}/reset-password?token={raw_token}"
        await asyncio.to_thread(send_password_reset_email, user.email, reset_url)

    return {"detail": "if that email exists, a reset link has been sent"}


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
) -> None:
    token_hash = _hash_reset_token(payload.token)
    result = await db.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    reset_token = result.scalar_one_or_none()

    if (
        reset_token is None
        or reset_token.used_at is not None
        or reset_token.expires_at < _utcnow()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid or expired token"
        )

    user = await db.get(User, reset_token.user_id)
    user.hashed_password = hash_password(payload.new_password)
    reset_token.used_at = _utcnow()
    await db.commit()
