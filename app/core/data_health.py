"""Checks on the tree's data: things that are probably typos. Read-only, nothing is fixed automatically.

`check_layout` is pure over a `TreeLayout` (so it never touches the database); `check_media` compares the media rows
with the files on disk. Findings of severity "info" are worth a look but not counted as issues on the admin home.
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import fold
from app.core.tree_layout import TreeLayout
from app.models.media import Media

MIN_PARENT_AGE = 12
MAX_PARENT_AGE = 70


@dataclass(frozen=True)
class Finding:
    kind: str
    severity: Literal["warning", "info"]
    member_id: int | None
    member_name: str | None
    message: str


def _warn(kind: str, member, message: str) -> Finding:
    return Finding(kind, "warning", member.id, member.full_name, message)


def check_layout(layout: TreeLayout) -> list[Finding]:
    found: list[Finding] = []
    by_key: dict[tuple[str, int], list] = defaultdict(list)
    for member in layout.by_id.values():
        if member.birth_year is not None and member.death_year is not None and member.death_year < member.birth_year:
            found.append(_warn("death_before_birth", member, f"Mất năm {member.death_year} trước khi sinh năm {member.birth_year}"))
    for member in layout.order:  # blood members only: spouses have no parent to compare with
        if member.birth_year is not None:
            by_key[(fold(member.full_name), member.birth_year)].append(member)
        parent = layout.by_id.get(member.parent_id) if member.parent_id is not None else None
        if parent is None or parent.birth_year is None or member.birth_year is None:
            continue
        gap = member.birth_year - parent.birth_year
        if gap < 0:
            found.append(_warn("child_before_parent", member, f"Sinh năm {member.birth_year}, trước cha {parent.full_name} ({parent.birth_year})"))
        elif gap < MIN_PARENT_AGE or gap > MAX_PARENT_AGE:
            found.append(_warn("parent_age_gap", member, f"Cách cha {parent.full_name} {gap} tuổi ({parent.birth_year} → {member.birth_year})"))
    for group in by_key.values():
        if len(group) > 1:
            for member in group:
                found.append(_warn("duplicate_name_year", member, f"Trùng tên và năm sinh với {len(group) - 1} người khác"))
    # a missing birth year above someone who has one (info only; a tree with no dates at all produces nothing)
    dated_below: dict[int, bool] = {}
    for member in reversed(layout.order):  # children come after their parent in depth-first order
        dated_below[member.id] = any(
            child.birth_year is not None or dated_below.get(child.id, False) for child in layout.children.get(member.id, [])
        )
    for member in layout.order:
        if member.birth_year is None and dated_below[member.id]:
            found.append(Finding("ancestor_gap_undated", "info", member.id, member.full_name, "Chưa có năm sinh, trong khi con cháu đã có"))
    return found


async def check_media(db: AsyncSession, tree_id: int, upload_dir: Path) -> list[Finding]:
    found: list[Finding] = []
    rows = (await db.execute(select(Media).where(Media.tree_id == tree_id).order_by(Media.id))).scalars().all()
    for row in rows:
        if not (upload_dir / "media" / row.stored_name).is_file():
            found.append(Finding("media_file_missing", "warning", row.member_id, None, f"{row.original_name} có trong dữ liệu nhưng file không còn trên máy chủ"))
        if row.member_id is None and row.place_id is None and row.article_id is None:
            found.append(Finding("media_orphan", "info", None, None, f"{row.original_name} không gắn với người, địa điểm hay bài viết nào"))
    return found
