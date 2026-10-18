"""Invitation links, public side (`/invite/<token>`): the token IS the access control, so every failure looks the same (404)."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.invites import hash_token, utcnow
from app.core.rate_limit import limit_by_ip
from app.core.roles import ROLE_MEMBER, STATUS_ACTIVE
from app.core.security import hash_password
from app.core.tenancy import is_paused
from app.db.session import get_db
from app.models.member import Member
from app.models.member_invite import MemberInvite
from app.models.tree import Tree
from app.models.user import User
from app.routers.auth import set_login_cookie
from app.schemas.search import PersonRef
from app.schemas.user import UserRead

router = APIRouter(prefix="/invite", tags=["invitations to join"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found")


class InvitePreview(BaseModel):
    family: str
    person: str
    expires_at: datetime


class AcceptInvite(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str | None = Field(default=None, max_length=255)


async def _open_invite(db: AsyncSession, token: str) -> tuple[MemberInvite, Member, Tree]:
    """The invitation behind `token` when it can still be used, else 404 (unknown, used, revoked, expired, family paused)."""
    invite = (await db.execute(select(MemberInvite).where(MemberInvite.token_hash == hash_token(token)))).scalar_one_or_none()
    if invite is None or invite.used_at is not None or invite.revoked_at is not None or invite.expires_at <= utcnow():
        raise _not_found()
    person = await db.get(Member, invite.member_id)
    tree = await db.get(Tree, invite.tree_id)
    if person is None or tree is None or is_paused(tree):
        raise _not_found()
    return invite, person, tree


@router.get("/{token}", response_model=InvitePreview)
async def view_invite(token: str, request: Request, db: AsyncSession = Depends(get_db)) -> InvitePreview:
    limit_by_ip(request, "invite", 30, 300)
    invite, person, tree = await _open_invite(db, token)
    return InvitePreview(family=tree.name, person=person.full_name, expires_at=invite.expires_at)


@router.post("/{token}/accept", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def accept_invite(
    token: str, payload: AcceptInvite, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> UserRead:
    limit_by_ip(request, "invite", 30, 300)
    invite, person, tree = await _open_invite(db, token)
    if (await db.execute(select(User.id).where(User.email == payload.email))).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")
    if (await db.execute(select(User.id).where(User.member_id == person.id))).first() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="that person already has an account")

    # Claim the link first, atomically: of two people racing for it exactly one gets a row back.
    now = utcnow()
    claimed = (
        await db.execute(
            update(MemberInvite)
            .where(
                MemberInvite.id == invite.id,
                MemberInvite.used_at.is_(None),
                MemberInvite.revoked_at.is_(None),
                MemberInvite.expires_at > now,
            )
            .values(used_at=now)
            .returning(MemberInvite.id)
        )
    ).first()
    if claimed is None:
        await db.rollback()
        raise _not_found()

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=(payload.full_name or "").strip() or person.full_name,
        role=ROLE_MEMBER,
        status=STATUS_ACTIVE,
        tree_id=tree.id,
        member_id=person.id,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:  # the same e-mail or person taken in the meantime: undo the claim too
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email or person already in use") from None
    await db.execute(update(MemberInvite).where(MemberInvite.id == invite.id).values(used_by=user.id))
    audit.record(
        db, tree_id=tree.id, actor=user, action="invite.accept", member_id=person.id, member_name=person.full_name,
        details={"invite_id": invite.id, "email": user.email},
    )
    await db.commit()
    await db.refresh(user)
    set_login_cookie(response, user.email)
    read = UserRead.model_validate(user)
    read.tree_name = tree.name
    read.member = PersonRef(id=person.id, name=person.full_name)
    return read
