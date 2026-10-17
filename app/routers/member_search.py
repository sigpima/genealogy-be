"""Search and basic statistics over one tree. Both are plain reads (an active user, or a guest on a public
tree) and both work on the tree loaded in memory - see `app/core/tree_layout.py` and the GĐ3 design for why
that is enough, and why folding diacritics happens here rather than in SQL.

Registered BEFORE `member.router` so `/members/search` is not taken for `/members/{member_id}`.
"""

import datetime
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.overview import compute_overview
from app.core.permissions import get_read_context
from app.core.tenancy import TreeContext
from app.core.text import fold
from app.core.tree_layout import TreeLayout, load_branches, load_layout, member_status
from app.db.session import get_db
from app.models.branch import Branch
from app.models.media import Media
from app.models.member import Member
from app.schemas.branch import BranchRef
from app.schemas.search import (
    BranchCount,
    GenderCounts,
    GenerationCount,
    PersonRef,
    SearchItem,
    SearchPage,
    Stats,
    StatusCounts,
)

router = APIRouter(tags=["search"])

SUGGESTION_MIN_RATIO = 0.6
MAX_SUGGESTIONS = 5


@dataclass
class Person:
    member: Member
    generation: int
    branch_id: int | None
    partner: Member | None = None  # set for a spouse


def _people(layout: TreeLayout, *, with_spouses: bool) -> list[Person]:
    people = [Person(m, layout.generation[m.id], layout.branch_of[m.id]) for m in layout.order]
    if with_spouses:
        for spouse in layout.spouses:
            generation = layout.generation_of(spouse.id)
            if generation is None:  # married into a member that is not on the blood line (should not happen)
                continue
            people.append(
                Person(spouse, generation, layout.branch_id_of(spouse.id), layout.by_id[layout.partner_of[spouse.id]])
            )
    return people


def _name_rank(query_tokens: list[str], folded_query: str, folded_name: str) -> int | None:
    """Lower is better; None = not a match. Every word of the query must occur in the name."""
    if not all(token in folded_name for token in query_tokens):
        return None
    if folded_name == folded_query:
        return 0
    if folded_name.startswith(folded_query):
        return 1
    words = folded_name.split()
    if all(any(word.startswith(token) for word in words) for token in query_tokens):
        return 2
    return 3


def _closeness(folded_query: str, folded_name: str) -> float:
    """How alike two folded names are, as the best of the whole name and (for a one-word query) any single word."""
    best = 0.0
    candidates = [folded_name] + (folded_name.split() if " " not in folded_query else [])
    for candidate in candidates:
        matcher = SequenceMatcher(None, folded_query, candidate)
        if matcher.real_quick_ratio() >= SUGGESTION_MIN_RATIO and matcher.quick_ratio() >= SUGGESTION_MIN_RATIO:
            best = max(best, matcher.ratio())
    return best


def _item(person: Person, layout: TreeLayout, branches: dict[int, Branch]) -> SearchItem:
    member = person.member
    parent = layout.by_id.get(member.parent_id) if member.parent_id is not None else None
    branch = branches.get(person.branch_id) if person.branch_id is not None else None
    return SearchItem(
        id=member.id,
        full_name=member.full_name,
        generation=person.generation,
        gender=member.gender,
        birth_year=member.birth_year,
        death_year=member.death_year,
        hometown=member.hometown,
        parent_name=parent.full_name if parent else None,
        branch=BranchRef(id=branch.id, name=branch.name, color=branch.color) if branch else None,
        is_spouse=person.partner is not None,
        spouse_of=PersonRef(id=person.partner.id, name=person.partner.full_name) if person.partner else None,
    )


async def _branch_scope(db: AsyncSession, ctx: TreeContext, branches: list[Branch], branch_id: int | None) -> int | None:
    """The head member id of the requested branch (404 for a branch of another tree or none at all)."""
    if branch_id is None:
        return None
    for branch in branches:
        if branch.id == branch_id:
            return branch.root_member_id
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="branch not found")


@router.get("/members/search", response_model=SearchPage)
async def search_members(
    q: str | None = None,
    generation: int | None = Query(default=None, ge=1),
    branch: int | None = None,
    born_from: int | None = None,
    born_to: int | None = None,
    hometown: str | None = None,
    gender: Literal["male", "female", "other", "unknown"] | None = None,
    status_: Literal["living", "deceased", "unknown"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_read_context),
) -> SearchPage:
    branches = await load_branches(db, ctx.tree.id)
    head_id = await _branch_scope(db, ctx, branches, branch)
    layout = await load_layout(db, ctx.tree.id, branches)
    branch_by_id = {b.id: b for b in branches}
    in_branch = layout.subtree_ids(head_id) if head_id is not None else None

    folded_query = fold(q or "")
    tokens = folded_query.split()
    folded_hometown = fold(hometown or "")
    this_year = datetime.date.today().year

    def passes_filters(person: Person) -> bool:
        member = person.member
        if generation is not None and person.generation != generation:
            return False
        if in_branch is not None and (person.partner or member).id not in in_branch:
            return False
        if born_from is not None or born_to is not None:
            if member.birth_year is None:
                return False
            if born_from is not None and member.birth_year < born_from:
                return False
            if born_to is not None and member.birth_year > born_to:
                return False
        if folded_hometown and folded_hometown not in fold(member.hometown or ""):
            return False
        if gender == "unknown" and member.gender is not None:
            return False
        if gender in ("male", "female", "other") and member.gender != gender:
            return False
        if status_ is not None and member_status(member.birth_year, member.death_year, this_year) != status_:
            return False
        return True

    candidates = [p for p in _people(layout, with_spouses=bool(tokens)) if passes_filters(p)]
    if tokens:
        ranked = []
        for person in candidates:
            rank = _name_rank(tokens, folded_query, fold(person.member.full_name))
            if rank is not None:
                ranked.append((rank, person.partner is not None, person.generation, person.member.id, person))
        ranked.sort(key=lambda r: r[:4])
        matches = [r[4] for r in ranked]
    else:
        matches = candidates  # tree order

    suggestions: list[SearchItem] = []
    if tokens and not matches:
        scored = [(_closeness(folded_query, fold(p.member.full_name)), p) for p in candidates]
        close = sorted((s for s in scored if s[0] >= SUGGESTION_MIN_RATIO), key=lambda s: (-s[0], s[1].member.id))
        # Suggestions are about what to type, so one entry per distinct name (namesakes would only add noise).
        seen: set[str] = set()
        unique = []
        for _, person in close:
            key = fold(person.member.full_name)
            if key not in seen:
                seen.add(key)
                unique.append(person)
        suggestions = [_item(p, layout, branch_by_id) for p in unique[:MAX_SUGGESTIONS]]

    page = matches[offset : offset + limit]
    return SearchPage(total=len(matches), items=[_item(p, layout, branch_by_id) for p in page], suggestions=suggestions)


@router.get("/stats", response_model=Stats)
async def stats(
    branch: int | None = None,
    db: AsyncSession = Depends(get_db),
    ctx: TreeContext = Depends(get_read_context),
) -> Stats:
    branches = await load_branches(db, ctx.tree.id)
    head_id = await _branch_scope(db, ctx, branches, branch)
    layout = await load_layout(db, ctx.tree.id, branches)
    scope = layout.subtree_ids(head_id) if head_id is not None else None
    members = [m for m in layout.order if scope is None or m.id in scope]
    this_year = datetime.date.today().year

    per_generation: dict[int, int] = {}
    per_branch: dict[int, int] = {}
    gender = GenderCounts()
    state = StatusCounts()
    without_branch = 0
    for member in members:
        per_generation[layout.generation[member.id]] = per_generation.get(layout.generation[member.id], 0) + 1
        key = member.gender if member.gender in ("male", "female", "other") else "unknown"
        setattr(gender, key, getattr(gender, key) + 1)
        key = member_status(member.birth_year, member.death_year, this_year)
        setattr(state, key, getattr(state, key) + 1)
        branch_id = layout.branch_of[member.id]
        if branch_id is None:
            without_branch += 1
        else:
            per_branch[branch_id] = per_branch.get(branch_id, 0) + 1
    in_scope = {m.id for m in members}
    spouses = sum(1 for s in layout.spouses if layout.partner_of[s.id] in in_scope)
    ordered_branches = sorted(
        (b for b in branches if b.id in per_branch),
        key=lambda b: (layout.generation.get(b.root_member_id, 0), b.id),
    )
    return Stats(
        total=len(members),
        spouses=spouses,
        by_generation=[GenerationCount(generation=g, count=c) for g, c in sorted(per_generation.items())],
        gender=gender,
        status=state,
        by_branch=[BranchCount(id=b.id, name=b.name, color=b.color, count=per_branch[b.id]) for b in ordered_branches],
        without_branch=without_branch,
    )


@router.get("/stats/overview")
async def stats_overview(db: AsyncSession = Depends(get_db), ctx: TreeContext = Depends(get_read_context)) -> dict:
    """Everything the statistics page shows (see app/core/overview.py). Aggregates only, so a public tree's guests get it too."""
    branches = await load_branches(db, ctx.tree.id)
    layout = await load_layout(db, ctx.tree.id, branches)
    with_photos = set(
        (await db.execute(select(Media.member_id).where(Media.tree_id == ctx.tree.id, Media.member_id.is_not(None)).distinct())).scalars().all()
    )
    return compute_overview(layout, branches, with_photos)
