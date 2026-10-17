"""Change requests: members propose, admins review (see the GĐ4 design).

A member never writes to the tree: the proposal is validated with the same rules as a direct edit, stored, and only
an admin's approval applies it - through the same code as a direct edit, so the audit log and every validation apply.
"""

import asyncio
import datetime
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import get_settings
from app.core.email import send_email
from app.core.permissions import get_user_context, get_write_context
from app.core.roles import ADMIN_ROLES, ROLE_ADMIN, STATUS_ACTIVE
from app.core.tenancy import TreeContext
from app.db.session import get_db
from app.models.change_request import ChangeRequest
from app.models.member import Member
from app.models.user import User
from app.routers.member import (
    WRITABLE_FIELDS,
    _apply_update,
    _member_in_tree,
    add_member,
    audit_member,
    member_values,
)
from app.schemas.change_request import (
    Decision,
    DiffRow,
    PersonName,
    RequestCreate,
    RequestPage,
    RequestRead,
    RequestSummary,
)
from app.schemas.member import MemberCreate, MemberUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/requests", tags=["change requests"])

# Everything a member may propose. Structure (parent, mother) stays with admins.
PROPOSABLE = tuple(f for f in WRITABLE_FIELDS if f not in ("parent_id", "mother_id"))
MIN_REPORT_LENGTH = 5


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def _plain(value: Any) -> Any:
    """A JSON-friendly value (enums such as Gender become their string)."""
    return getattr(value, "value", value)


def _validate(model: type[MemberUpdate] | type[MemberCreate], data: dict[str, Any]) -> Any:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_context=False)) from None


def _unknown_fields(changes: dict[str, Any]) -> list[str]:
    return sorted(set(changes) - set(PROPOSABLE))


# --------------------------------------------------------------------------- reading


def _diff(req: ChangeRequest, member: Member | None) -> list[DiffRow]:
    rows = []
    for field_name, new in req.changes.items():
        if req.kind == "add_child":
            rows.append(DiffRow(field=field_name, old=None, new=new))
            continue
        base = req.base.get(field_name)
        if req.status == "pending" and member is not None:
            current = _plain(getattr(member, field_name))
            rows.append(DiffRow(field=field_name, old=current, new=new, stale=current != base))
        else:
            rows.append(DiffRow(field=field_name, old=base, new=new))
    return rows


async def _read(db: AsyncSession, req: ChangeRequest) -> RequestRead:
    member = await db.get(Member, req.member_id) if req.member_id is not None else None
    diff = _diff(req, member)
    return RequestRead(
        id=req.id,
        kind=req.kind,
        status=req.status,
        member_id=req.member_id,
        member_name=member.full_name if member else req.member_name,
        message=req.message,
        changes=req.changes,
        base=req.base,
        diff=diff,
        stale=any(d.stale for d in diff),
        requester=PersonName(id=req.requester_id, name=req.requester_name),
        reviewer=PersonName(id=req.reviewer_id, name=req.reviewer_name) if req.reviewer_name else None,
        review_note=req.review_note,
        result_member_id=req.result_member_id,
        created_at=req.created_at,
        reviewed_at=req.reviewed_at,
    )


def _is_admin(ctx: TreeContext) -> bool:
    return ctx.user is not None and ctx.user.role in ADMIN_ROLES


async def _visible(db: AsyncSession, ctx: TreeContext, request_id: int) -> ChangeRequest:
    """The request if it is in this tree and the caller may see it (admins: all; others: their own); else 404."""
    req = await db.get(ChangeRequest, request_id)
    if req is None or req.tree_id != ctx.tree.id or not (_is_admin(ctx) or req.requester_id == ctx.user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request not found")
    return req


@router.get("/summary", response_model=RequestSummary)
async def summary(db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_user_context)) -> RequestSummary:
    conditions = [ChangeRequest.tree_id == ctx.tree.id, ChangeRequest.status == "pending"]
    if not _is_admin(ctx):
        conditions.append(ChangeRequest.requester_id == ctx.user.id)
    count = (await db.execute(select(func.count()).select_from(ChangeRequest).where(*conditions))).scalar_one()
    return RequestSummary(pending=count)


@router.get("", response_model=RequestPage)
async def list_requests(
    status_: Literal["pending", "approved", "rejected", "cancelled", "closed"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_user_context),
) -> RequestPage:
    conditions = [ChangeRequest.tree_id == ctx.tree.id]
    if not _is_admin(ctx):
        conditions.append(ChangeRequest.requester_id == ctx.user.id)
    if status_ == "closed":
        conditions.append(ChangeRequest.status != "pending")
    elif status_ is not None:
        conditions.append(ChangeRequest.status == status_)
    total = (await db.execute(select(func.count()).select_from(ChangeRequest).where(*conditions))).scalar_one()
    rows = (
        await db.execute(select(ChangeRequest).where(*conditions).order_by(ChangeRequest.id.desc()).limit(limit).offset(offset))
    ).scalars().all()
    return RequestPage(total=total, items=[await _read(db, r) for r in rows])


@router.get("/{request_id}", response_model=RequestRead)
async def get_request(request_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_user_context)) -> RequestRead:
    return await _read(db, await _visible(db, ctx, request_id))


# --------------------------------------------------------------------------- notifications


async def _notify(recipients: list[str], subject: str, body: str) -> None:
    """Best-effort email: nothing configured or a failing server must never block or fail the action."""
    if not get_settings().smtp_host:
        return
    for address in recipients:
        try:
            await asyncio.to_thread(send_email, address, subject, body)
        except Exception:  # noqa: BLE001 - any SMTP/network error is only worth a log line
            logger.warning("could not email %s about a change request", address, exc_info=True)


KIND_LABELS = {"edit": "đề xuất sửa", "add_child": "đề xuất thêm con", "report": "báo sai/bổ sung"}


# --------------------------------------------------------------------------- proposing


@router.post("", response_model=RequestRead, status_code=status.HTTP_201_CREATED)
async def create_request(
    payload: RequestCreate, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_user_context)
) -> RequestRead:
    member = await _member_in_tree(db, ctx.tree.id, payload.member_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    unknown = _unknown_fields(payload.changes)
    if unknown:
        raise _unprocessable(f"these fields cannot be proposed: {', '.join(unknown)}")

    changes: dict[str, Any] = {}
    base: dict[str, Any] = {}
    if payload.kind == "report":
        if payload.changes:
            raise _unprocessable("a report carries a message, not field changes")
        if len(payload.message or "") < MIN_REPORT_LENGTH:
            raise _unprocessable(f"describe what is wrong or missing (at least {MIN_REPORT_LENGTH} characters)")
    elif payload.kind == "edit":
        if not payload.changes:
            raise _unprocessable("nothing was proposed")
        current = member_values(member)
        checked = _validate(MemberUpdate, {**current, **payload.changes})
        for field_name in payload.changes:
            new = _plain(getattr(checked, field_name))
            if new != current[field_name]:
                changes[field_name] = new
                base[field_name] = current[field_name]
        if not changes:
            raise _unprocessable("the proposal changes nothing")
    else:  # add_child
        if not str(payload.changes.get("full_name") or "").strip():
            raise _unprocessable("a new child needs a name")
        checked = _validate(MemberCreate, {**payload.changes, "parent_id": member.id})
        changes = {name: _plain(getattr(checked, name)) for name in payload.changes}

    req = ChangeRequest(
        tree_id=ctx.tree.id,
        member_id=member.id,
        member_name=member.full_name,
        requester_id=ctx.user.id,
        requester_name=ctx.user.full_name,
        kind=payload.kind,
        status="pending",
        changes=changes,
        base=base,
        message=payload.message,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)

    admins = (
        await db.execute(
            select(User.email).where(User.tree_id == ctx.tree.id, User.role == ROLE_ADMIN, User.status == STATUS_ACTIVE)
        )
    ).scalars().all()
    await _notify(
        [email for email in admins if email != ctx.user.email],
        f"[{ctx.tree.name}] Yêu cầu mới: {KIND_LABELS[req.kind]} {member.full_name}",
        f"{ctx.user.full_name} vừa gửi một yêu cầu ({KIND_LABELS[req.kind]}) về {member.full_name}.\n\n"
        f"{payload.message or ''}\n\nVào mục Yêu cầu trên trang gia phả để xem và duyệt.",
    )
    return await _read(db, req)


# --------------------------------------------------------------------------- deciding


async def _pending_in_tree(db: AsyncSession, ctx: TreeContext, request_id: int) -> ChangeRequest:
    req = await db.get(ChangeRequest, request_id)
    if req is None or req.tree_id != ctx.tree.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request not found")
    if req.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"request already {req.status}")
    return req


def _close(req: ChangeRequest, ctx: TreeContext, new_status: str, note: str | None) -> None:
    req.status = new_status
    req.reviewer_id = ctx.user.id
    req.reviewer_name = ctx.user.full_name
    req.review_note = note
    req.reviewed_at = datetime.datetime.now(datetime.timezone.utc)


async def _tell_requester(db: AsyncSession, req: ChangeRequest, ctx: TreeContext, outcome: str) -> None:
    if req.requester_id is None:
        return
    requester = await db.get(User, req.requester_id)
    if requester is None or requester.id == ctx.user.id:
        return
    await _notify(
        [requester.email],
        f"[{ctx.tree.name}] Yêu cầu của bạn {outcome}",
        f"Yêu cầu ({KIND_LABELS[req.kind]}) về {req.member_name} đã được {outcome} bởi {ctx.user.full_name}.\n\n"
        f"{req.review_note or ''}",
    )


@router.post("/{request_id}/approve", response_model=RequestRead)
async def approve(
    request_id: int,
    decision: Decision,
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> RequestRead:
    req = await _pending_in_tree(db, ctx, request_id)
    member = await _member_in_tree(db, ctx.tree.id, req.member_id) if req.member_id is not None else None
    if req.kind != "report" and member is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="the person no longer exists")
    try:
        if req.kind == "edit":
            payload = MemberUpdate.model_validate({**member_values(member), **req.changes})
            await _apply_update(db, ctx, member, payload, commit=False, request_id=req.id)
        elif req.kind == "add_child":
            created = await add_member(
                db, ctx, MemberCreate.model_validate({**req.changes, "parent_id": member.id}), request_id=req.id
            )
            req.result_member_id = created.id
    except (ValidationError, HTTPException):
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the proposal no longer fits the current data; reject it or ask for a new one",
        ) from None
    _close(req, ctx, "approved", decision.note)
    audit.record(
        db,
        tree_id=ctx.tree.id,
        actor=ctx.user,
        action="request.approve",
        member_id=req.member_id,
        member_name=req.member_name,
        details={"kind": req.kind, "note": decision.note},
        request_id=req.id,
    )
    await db.commit()
    await db.refresh(req)
    await _tell_requester(db, req, ctx, "chấp nhận")
    return await _read(db, req)


@router.post("/{request_id}/reject", response_model=RequestRead)
async def reject(
    request_id: int,
    decision: Decision,
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_write_context),
) -> RequestRead:
    if not decision.note:
        raise _unprocessable("give a reason")
    req = await _pending_in_tree(db, ctx, request_id)
    _close(req, ctx, "rejected", decision.note)
    audit.record(
        db,
        tree_id=ctx.tree.id,
        actor=ctx.user,
        action="request.reject",
        member_id=req.member_id,
        member_name=req.member_name,
        details={"kind": req.kind, "note": decision.note},
        request_id=req.id,
    )
    await db.commit()
    await db.refresh(req)
    await _tell_requester(db, req, ctx, "từ chối")
    return await _read(db, req)


@router.post("/{request_id}/cancel", response_model=RequestRead)
async def cancel(
    request_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_user_context)
) -> RequestRead:
    req = await db.get(ChangeRequest, request_id)
    # Only the requester withdraws a request; an admin decides it instead. Anyone else gets 404.
    if req is None or req.tree_id != ctx.tree.id or req.requester_id != ctx.user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request not found")
    if req.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"request already {req.status}")
    req.status = "cancelled"
    req.reviewed_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()
    await db.refresh(req)
    return await _read(db, req)
