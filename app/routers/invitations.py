"""Invitation cards with a secret link and RSVPs (see the GĐ9 design).

Two audiences: admins manage cards (`/events/{id}/cards`, `/cards/...`); anybody with a link answers without logging in
(`/invitations/{token}`). The public side reveals the event and the totals, never other guests' names or notes.
"""

import csv
import io
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, calendar_items
from app.core.audit import diff_values
from app.core.lunar import solar_to_lunar
from app.core.permissions import get_write_context
from app.core.rate_limit import limit_by_ip
from app.core.tenancy import TreeContext
from app.db.session import get_db
from app.models.event import Event
from app.models.event_card import EventCard, EventRsvp
from app.models.place import Place
from app.models.tree import Tree
from app.routers.calendar import lunar_out
from app.schemas.invitation import (
    CardCreate,
    CardDetail,
    CardRead,
    CardUpdate,
    Counts,
    Guest,
    InviteesIn,
    PlaceInfo,
    PublicCard,
    PublicTotals,
    RespondIn,
    RespondResult,
    RsvpRead,
)

public_router = APIRouter(prefix="/invitations", tags=["invitations (public)"])
admin_router = APIRouter(tags=["invitations"])

MAX_RESPONSES = 500  # an open link must not become a storage dump
RESPONSE_LABELS = {"yes": "tham dự", "no": "không tham dự", "maybe": "chưa chắc", None: "chưa trả lời"}


def _token() -> str:
    return secrets.token_urlsafe(24)


def _expired(card: EventCard) -> bool:
    return card.closes_on is not None and calendar_items.vn_today() > card.closes_on


async def _counts(db: AsyncSession, card_id: int) -> Counts:
    rows = (
        await db.execute(
            select(EventRsvp.response, func.count(), func.coalesce(func.sum(EventRsvp.party_size), 0))
            .where(EventRsvp.card_id == card_id)
            .group_by(EventRsvp.response)
        )
    ).all()
    counts = Counts()
    for response, n, people in rows:
        if response is None:
            counts.pending = n
        else:
            setattr(counts, response, n)
        if response == "yes":
            counts.people = int(people)
    return counts


async def _read(db: AsyncSession, card: EventCard) -> CardRead:
    event = await db.get(Event, card.event_id)
    return CardRead(
        id=card.id,
        event_id=card.event_id,
        event_title=event.title,
        date=card.date,
        token=card.token,
        path=f"/thiep/{card.token}",
        message=card.message,
        closes_on=card.closes_on,
        closed=card.closed,
        expired=_expired(card),
        counts=await _counts(db, card.id),
    )


def _rsvp_read(r: EventRsvp) -> RsvpRead:
    return RsvpRead(
        id=r.id,
        name=r.name,
        response=r.response,
        party_size=r.party_size,
        note=r.note,
        personal_token=r.invitee_token,
        path=f"/thiep/{r.invitee_token}",
        responded_at=r.responded_at,
    )


async def _card_in_tree(db: AsyncSession, ctx: TreeContext, card_id: int) -> EventCard:
    card = await db.get(EventCard, card_id)
    if card is None or card.tree_id != ctx.tree.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="card not found")
    return card


async def _event_in_tree(db: AsyncSession, ctx: TreeContext, event_id: int) -> Event:
    event = await db.get(Event, event_id)
    if event is None or event.tree_id != ctx.tree.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="event not found")
    return event


def _audit(db: AsyncSession, ctx: TreeContext, action: str, card: EventCard, title: str, changes: dict | None = None) -> None:
    audit.record(
        db,
        tree_id=ctx.tree.id,
        actor=ctx.user,
        action=action,
        changes=changes,
        details={"card_id": card.id, "event_title": title, "date": card.date.isoformat()},
    )


# --------------------------------------------------------------------------- admin


@admin_router.get("/cards", response_model=list[CardRead])
async def list_all_cards(
    open: bool = False, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)  # noqa: A002 (query name)
) -> list[CardRead]:
    """Every card of this tree, newest first; `open=true` keeps those that still take answers (not closed, deadline not passed)."""
    cards = (
        await db.execute(select(EventCard).where(EventCard.tree_id == ctx.tree.id).order_by(EventCard.date.desc(), EventCard.id.desc()))
    ).scalars().all()
    if open:
        cards = [c for c in cards if not c.closed and not _expired(c)]
    return [await _read(db, c) for c in cards]


@admin_router.get("/events/{event_id}/cards", response_model=list[CardRead])
async def list_cards(event_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> list[CardRead]:
    await _event_in_tree(db, ctx, event_id)
    cards = (
        await db.execute(select(EventCard).where(EventCard.event_id == event_id).order_by(EventCard.date.desc(), EventCard.id.desc()))
    ).scalars().all()
    return [await _read(db, c) for c in cards]


@admin_router.post("/events/{event_id}/cards", response_model=CardRead, status_code=status.HTTP_201_CREATED)
async def create_card(
    event_id: int, payload: CardCreate, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> CardRead:
    event = await _event_in_tree(db, ctx, event_id)
    if not calendar_items.event_items([event], payload.date, payload.date):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="that date is not an occurrence of this event")
    card = EventCard(
        tree_id=ctx.tree.id,
        event_id=event.id,
        date=payload.date,
        token=_token(),
        message=payload.message,
        closes_on=payload.closes_on,
        created_by=ctx.user.id,
    )
    db.add(card)
    await db.flush()
    _audit(db, ctx, "card.create", card, event.title)
    await db.commit()
    await db.refresh(card)
    return await _read(db, card)


@admin_router.get("/cards/{card_id}", response_model=CardDetail)
async def get_card(card_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> CardDetail:
    card = await _card_in_tree(db, ctx, card_id)
    rows = (await db.execute(select(EventRsvp).where(EventRsvp.card_id == card.id).order_by(EventRsvp.id))).scalars().all()
    return CardDetail(**(await _read(db, card)).model_dump(), responses=[_rsvp_read(r) for r in rows])


@admin_router.patch("/cards/{card_id}", response_model=CardRead)
async def update_card(
    card_id: int, payload: CardUpdate, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> CardRead:
    card = await _card_in_tree(db, ctx, card_id)

    def snapshot() -> dict:
        return {"message": card.message, "closes_on": card.closes_on.isoformat() if card.closes_on else None, "closed": card.closed}

    before = snapshot()
    sent = payload.model_fields_set
    if "message" in sent:
        card.message = payload.message
    if "closes_on" in sent:
        card.closes_on = payload.closes_on
    if "closed" in sent and payload.closed is not None:
        card.closed = payload.closed
    changes = diff_values(before, snapshot())
    if changes:
        event = await db.get(Event, card.event_id)
        _audit(db, ctx, "card.update", card, event.title, changes)
    await db.commit()
    await db.refresh(card)
    return await _read(db, card)


@admin_router.delete("/cards/{card_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_card(card_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> None:
    card = await _card_in_tree(db, ctx, card_id)
    event = await db.get(Event, card.event_id)
    _audit(db, ctx, "card.delete", card, event.title)
    await db.delete(card)
    await db.commit()


@admin_router.post("/cards/{card_id}/invitees", response_model=list[RsvpRead], status_code=status.HTTP_201_CREATED)
async def add_invitees(
    card_id: int, payload: InviteesIn, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> list[RsvpRead]:
    """Personal links: one per name (blank and repeated names are dropped)."""
    card = await _card_in_tree(db, ctx, card_id)
    names = list(dict.fromkeys(n.strip() for n in payload.names if n.strip()))
    if not names or any(len(n) > 150 for n in names):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="give 1-200 names of at most 150 characters")
    existing = (await db.execute(select(func.count()).select_from(EventRsvp).where(EventRsvp.card_id == card.id))).scalar_one()
    if existing + len(names) > MAX_RESPONSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="too many guests on this card")
    rows = [EventRsvp(card_id=card.id, name=n, invitee_token=_token()) for n in names]
    db.add_all(rows)
    await db.commit()
    return [_rsvp_read(r) for r in rows]


@admin_router.delete("/cards/{card_id}/responses/{rsvp_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_response(
    card_id: int, rsvp_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)
) -> None:
    card = await _card_in_tree(db, ctx, card_id)
    row = await db.get(EventRsvp, rsvp_id)
    if row is None or row.card_id != card.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="response not found")
    await db.delete(row)
    await db.commit()


@admin_router.get("/cards/{card_id}/export.csv")
async def export_responses(card_id: int, db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_write_context)) -> Response:
    card = await _card_in_tree(db, ctx, card_id)
    rows = (await db.execute(select(EventRsvp).where(EventRsvp.card_id == card.id).order_by(EventRsvp.id))).scalars().all()
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["name", "response", "party_size", "note", "responded_at"])
    for r in rows:
        writer.writerow(
            [r.name, RESPONSE_LABELS[r.response], r.party_size if r.response == "yes" else "", r.note or "", r.responded_at.isoformat() if r.responded_at else ""]
        )
    return Response(
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="phan-hoi-{card.date.isoformat()}.csv"'},
    )


# --------------------------------------------------------------------------- public (a secret link is the access control)


async def _resolve(db: AsyncSession, token: str) -> tuple[EventCard, EventRsvp | None]:
    rsvp = (await db.execute(select(EventRsvp).where(EventRsvp.invitee_token == token))).scalar_one_or_none()
    if rsvp is not None:
        return await db.get(EventCard, rsvp.card_id), rsvp
    card = (await db.execute(select(EventCard).where(EventCard.token == token))).scalar_one_or_none()
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    return card, None


async def _public(db: AsyncSession, card: EventCard, rsvp: EventRsvp | None) -> PublicCard:
    event = await db.get(Event, card.event_id)
    tree = await db.get(Tree, card.tree_id)
    place = await db.get(Place, event.place_id) if event.place_id is not None else None
    counts = await _counts(db, card.id)
    return PublicCard(
        family=tree.name,
        title=event.title,
        kind=event.kind,
        date=card.date,
        lunar=lunar_out(solar_to_lunar(card.date)),
        time_text=event.time_text,
        message=card.message,
        place=PlaceInfo(name=place.name, address=place.address, latitude=place.latitude, longitude=place.longitude) if place else None,
        closed=card.closed or _expired(card),
        totals=PublicTotals(yes=counts.yes, people=counts.people),
        guest=Guest(name=rsvp.name, response=rsvp.response, party_size=rsvp.party_size, note=rsvp.note) if rsvp else None,
    )


@public_router.get("/{token}", response_model=PublicCard)
async def view(token: str, db: AsyncSession = Depends(get_db)) -> PublicCard:
    card, rsvp = await _resolve(db, token)
    return await _public(db, card, rsvp)


@public_router.post("/{token}/respond", response_model=RespondResult)
async def respond(token: str, payload: RespondIn, request: Request, db: AsyncSession = Depends(get_db)) -> RespondResult:
    limit_by_ip(request, "rsvp", 40, 600)
    card, rsvp = await _resolve(db, token)
    if card.closed or _expired(card):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="this invitation is closed")
    if rsvp is None:  # the open link: a new guest, who must give a name
        if not payload.name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="name is required")
        total = (await db.execute(select(func.count()).select_from(EventRsvp).where(EventRsvp.card_id == card.id))).scalar_one()
        if total >= MAX_RESPONSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="this invitation has reached its limit of answers")
        rsvp = EventRsvp(card_id=card.id, name=payload.name, invitee_token=_token())
        db.add(rsvp)
    sent = payload.model_fields_set
    rsvp.response = payload.response
    # Changing an answer keeps what the guest did not send again (a note, the number of people); sending null/blank clears the note.
    if rsvp.id is None or "party_size" in sent:
        rsvp.party_size = payload.party_size
    if rsvp.id is None or "note" in sent:
        rsvp.note = payload.note
    rsvp.responded_at = func.now()
    await db.commit()
    await db.refresh(rsvp)
    result = await _public(db, card, rsvp)
    return RespondResult(**result.model_dump(), token=rsvp.invitee_token)
