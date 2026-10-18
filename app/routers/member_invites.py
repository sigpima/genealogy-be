"""Invitation links, admin side: one link per person, shown once, revoked by making a new one or by hand."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.invites import LIFETIME, hash_token, invite_status, new_token, utcnow
from app.core.permissions import get_write_context
from app.core.tenancy import TreeContext
from app.db.session import get_db
from app.models.member import Member
from app.models.member_invite import MemberInvite
from app.models.user import User
from app.schemas.member_invite import InviteCreated, InviteRead
from app.schemas.search import PersonRef

router = APIRouter(tags=["member invitations"])


@router.post("/members/{member_id}/invitation", response_model=InviteCreated, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    member_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> InviteCreated:
    person = await db.get(Member, member_id)
    if person is None or person.tree_id != ctx.tree.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    linked = (await db.execute(select(User.id).where(User.member_id == member_id))).first()
    if linked is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="that person already has an account")

    now = utcnow()
    await db.execute(
        update(MemberInvite)
        .where(MemberInvite.member_id == member_id, MemberInvite.used_at.is_(None), MemberInvite.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    token = new_token()
    invite = MemberInvite(
        tree_id=ctx.tree.id,
        member_id=member_id,
        token_hash=hash_token(token),
        created_by=ctx.user.id,
        expires_at=now + LIFETIME,
    )
    db.add(invite)
    try:
        await db.flush()
    except IntegrityError:  # two admins pressing at once: the other one's link won
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="another invitation was just made, try again") from None
    audit.record(
        db, tree_id=ctx.tree.id, actor=ctx.user, action="invite.create", member_id=member_id, member_name=person.full_name,
        details={"invite_id": invite.id, "expires_at": invite.expires_at.isoformat()},
    )
    await db.commit()
    return InviteCreated(id=invite.id, path=f"/moi/{token}", expires_at=invite.expires_at)


@router.get("/admin/invitations", response_model=list[InviteRead])
async def list_invitations(db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> list[InviteRead]:
    rows = (
        await db.execute(
            select(MemberInvite, Member.full_name, User.email)
            .join(Member, Member.id == MemberInvite.member_id)
            .outerjoin(User, User.id == MemberInvite.used_by)
            .where(MemberInvite.tree_id == ctx.tree.id)
            .order_by(MemberInvite.id.desc())
        )
    ).all()
    now = utcnow()
    return [
        InviteRead(
            id=invite.id,
            member=PersonRef(id=invite.member_id, name=name),
            status=invite_status(invite, now),
            created_at=invite.created_at,
            expires_at=invite.expires_at,
            used_at=invite.used_at,
            used_by_email=email,
        )
        for invite, name, email in rows
    ]


@router.delete("/invitations/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(invite_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> Response:
    invite = await db.get(MemberInvite, invite_id)
    if invite is None or invite.tree_id != ctx.tree.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found")
    if invite.revoked_at is None and invite.used_at is None:
        invite.revoked_at = utcnow()
        person = await db.get(Member, invite.member_id)
        audit.record(
            db, tree_id=ctx.tree.id, actor=ctx.user, action="invite.revoke", member_id=invite.member_id,
            member_name=person.full_name if person else None, details={"invite_id": invite.id},
        )
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
