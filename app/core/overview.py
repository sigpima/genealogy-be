"""The statistics overview, computed over the tree loaded in memory (see GĐ8 design). Pure functions of a `TreeLayout`."""

import datetime
import statistics
from collections import Counter

from app.core.text import fold
from app.core.tree_layout import TreeLayout, member_status
from app.models.branch import Branch
from app.models.member import Member

MAX_LIFESPAN = 120
TOP_NAMES = 10

COMPLETENESS_FIELDS = (
    ("gender", "Giới tính"),
    ("birth_year", "Năm sinh"),
    ("birth_date", "Ngày và tháng sinh"),
    ("hometown", "Quê quán"),
    ("residence", "Nơi ở"),
    ("avatar", "Ảnh đại diện"),
    ("photos", "Có ảnh / tài liệu"),
)


def _lifespans(members: list[Member]) -> list[tuple[int, str | None]]:
    out = []
    for m in members:
        if m.birth_year is not None and m.death_year is not None and 0 <= m.death_year - m.birth_year <= MAX_LIFESPAN:
            out.append((m.death_year - m.birth_year, m.gender))
    return out


def _round(value: float) -> float:
    return round(value, 1)


def _top_words(names: list[str]) -> list[dict]:
    """Most common words, counted with accents folded and shown in their most common spelling."""
    counts: Counter[str] = Counter()
    spellings: dict[str, Counter[str]] = {}
    for word in names:
        key = fold(word)
        counts[key] += 1
        spellings.setdefault(key, Counter())[word] += 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_NAMES]
    return [{"word": spellings[key].most_common(1)[0][0], "count": n} for key, n in ranked]


def compute_overview(
    layout: TreeLayout,
    branches: list[Branch],
    photo_owner_ids: set[int],
    this_year: int | None = None,
) -> dict:
    this_year = this_year or datetime.date.today().year
    members = layout.order
    total = len(members)

    status = Counter(member_status(m.birth_year, m.death_year, this_year) for m in members)
    gender = Counter(m.gender if m.gender in ("male", "female", "other") else "unknown" for m in members)

    per_generation: dict[int, Counter[str]] = {}
    for m in members:
        counter = per_generation.setdefault(layout.generation[m.id], Counter())
        counter["count"] += 1
        if m.gender in ("male", "female"):
            counter[m.gender] += 1

    branch_counts: Counter[int] = Counter()
    without_branch = 0
    for m in members:
        branch_id = layout.branch_of[m.id]
        if branch_id is None:
            without_branch += 1
        else:
            branch_counts[branch_id] += 1
    ordered_branches = sorted((b for b in branches if branch_counts[b.id]), key=lambda b: (layout.generation.get(b.root_member_id, 0), b.id))

    ages = _lifespans(members)
    values = [a for a, _ in ages]
    by_gender = {g: [a for a, sex in ages if sex == g] for g in ("male", "female")}
    lifespan = {
        "count": len(values),
        "average": _round(statistics.mean(values)) if values else None,
        "median": _round(statistics.median(values)) if values else None,
        "shortest": min(values) if values else None,
        "longest": max(values) if values else None,
        "male_average": _round(statistics.mean(by_gender["male"])) if by_gender["male"] else None,
        "female_average": _round(statistics.mean(by_gender["female"])) if by_gender["female"] else None,
    }

    decades = Counter(m.birth_year // 10 * 10 for m in members if m.birth_year is not None)

    child_counts = {m.id: len(layout.children.get(m.id, [])) for m in members}
    parents = [(mid, n) for mid, n in child_counts.items() if n > 0]
    most = max(parents, key=lambda p: (p[1], -p[0]), default=None)
    children = {
        "parents": len(parents),
        "average_per_parent": _round(sum(n for _, n in parents) / len(parents)) if parents else None,
        "childless": total - len(parents),
        "most": {"id": most[0], "name": layout.by_id[most[0]].full_name, "count": most[1]} if most else None,
    }

    # the first deepest person in tree order, then walk up to the root
    deepest: Member | None = None
    if members:
        top = max(layout.generation[m.id] for m in members)
        deepest = next(m for m in members if layout.generation[m.id] == top)
    chain: list[str] = []
    cursor: Member | None = deepest
    while cursor is not None:
        chain.append(cursor.full_name)
        cursor = layout.by_id.get(cursor.parent_id) if cursor.parent_id is not None else None
    chain.reverse()
    longest_line = {"generations": len(chain), "names": chain}

    middle, given = [], []
    for m in members:
        words = m.full_name.split()
        if len(words) >= 3:
            middle.append(words[1])
        if len(words) >= 2:
            given.append(words[-1])

    have = {
        "gender": sum(m.gender is not None for m in members),
        "birth_year": sum(m.birth_year is not None for m in members),
        "birth_date": sum(m.birth_month is not None and m.birth_day is not None for m in members),
        "hometown": sum(m.hometown is not None for m in members),
        "residence": sum(m.residence is not None for m in members),
        "avatar": sum(m.avatar_url is not None for m in members),
        "photos": sum(m.id in photo_owner_ids for m in members),
    }

    return {
        "totals": {
            "members": total,
            "spouses": len(layout.spouses),
            "generations": max(per_generation) if per_generation else 0,
            "living": status["living"],
            "deceased": status["deceased"],
            "unknown": status["unknown"],
        },
        "gender": {key: gender[key] for key in ("male", "female", "other", "unknown")},
        "by_generation": [
            {"generation": g, "count": c["count"], "male": c["male"], "female": c["female"]} for g, c in sorted(per_generation.items())
        ],
        "by_branch": [{"id": b.id, "name": b.name, "color": b.color, "count": branch_counts[b.id]} for b in ordered_branches],
        "without_branch": without_branch,
        "lifespan": lifespan,
        "birth_decades": [{"decade": d, "count": n} for d, n in sorted(decades.items())],
        "children": children,
        "longest_line": longest_line,
        "middle_names": _top_words(middle),
        "given_names": _top_words(given),
        "completeness": [{"field": key, "label": label, "have": have[key], "total": total} for key, label in COMPLETENESS_FIELDS],
    }
