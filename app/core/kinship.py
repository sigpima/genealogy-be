"""Who is who to whom, in Vietnamese kinship terms (GĐ11 B4; see the design).

Works on the blood line (`parent_id` = father) of a `TreeLayout`. A spouse is reached through their partner. Maternal
relatives (cậu, dì...) are not in the tree - the mother is a spouse, not a parent - so they cannot appear here.
"""

from dataclasses import dataclass

from app.core.tree_layout import TreeLayout
from app.models.member import Member


@dataclass
class Relation:
    kind: str  # self | spouse | blood | in_law | none
    a_is: str | None = None  # what A is to B
    b_is: str | None = None  # what B is to A
    sentence: str = ""
    common_ancestor: Member | None = None
    steps_a: int | None = None  # generations from the common ancestor down to A
    steps_b: int | None = None


def _older(x: Member, y: Member) -> bool | None:
    """Is x older than y? Manual birth order first, then birth year; None when it cannot be told."""
    if x.birth_order is not None and y.birth_order is not None and x.birth_order != y.birth_order:
        return x.birth_order < y.birth_order
    if x.birth_year is not None and y.birth_year is not None and x.birth_year != y.birth_year:
        return x.birth_year < y.birth_year
    return None


def _by_gender(x: Member, male: str, female: str, unknown: str) -> str:
    return male if x.gender == "male" else female if x.gender == "female" else unknown


def _sibling_term(x: Member, older: bool | None, suffix: str = "") -> str:
    if older is None:
        term = _by_gender(x, "anh/em trai", "chị/em gái", "anh chị em")
    elif older:
        term = _by_gender(x, "anh", "chị", "anh/chị")
    else:
        term = _by_gender(x, "em trai", "em gái", "em")
    return term + suffix


def _ancestor_term(x: Member, steps: int) -> str:
    if steps == 1:
        return _by_gender(x, "cha", "mẹ", "cha/mẹ")
    if steps == 2:
        return _by_gender(x, "ông", "bà", "ông/bà")
    if steps == 3:
        return _by_gender(x, "cụ ông", "cụ bà", "cụ")
    if steps == 4:
        return _by_gender(x, "kỵ ông", "kỵ bà", "kỵ")
    return f"tổ tiên (trên {steps} đời)"


def _descendant_term(steps: int) -> str:
    return {1: "con", 2: "cháu", 3: "chắt", 4: "chút"}.get(steps, f"con cháu (dưới {steps} đời)")


def _blood_term(x: Member, y: Member, dx: int, dy: int, cx: Member | None, cy: Member | None) -> str:
    """What x is to y, given x and y are `dx`/`dy` steps below their common ancestor (cx/cy: the ancestor's children on each path)."""
    if dx == 0:
        return _ancestor_term(x, dy)
    if dy == 0:
        return _descendant_term(dx)
    if dx == 1 and dy == 1:
        return _sibling_term(x, _older(x, y))
    if dx == dy:  # cousins: ranked by the order of their branches (cx/cy), not by age
        suffix = {2: "", 3: " (cùng cụ)", 4: " (cùng kỵ)"}.get(dx, f" (cùng tổ {dx} đời trên)")
        older = _older(cx, cy)
        base = "anh chị em" if older is None else _by_gender(x, "anh", "chị", "anh/chị") if older else "em"
        return base + " họ" + suffix
    ho = " họ" if dx >= 2 and dy >= 2 else ""
    if dx < dy:  # x belongs to an older generation: bác / chú / cô
        gap = dy - dx
        older = _older(cx, cy)
        if older:
            base = "bác"
        else:
            base = _by_gender(x, "chú", "cô", "chú/cô") if older is False else _by_gender(x, "chú/bác", "cô/bác", "chú/bác/cô")
        if gap == 1:
            return base + ho
        if gap == 2:
            return {"bác": "ông bác", "chú": "ông chú", "cô": "bà cô"}.get(base, f"ông/bà ({base})") + ho
        if gap == 3:
            return "cụ " + base + ho
        return f"{base}{ho} (bậc trên {gap} đời)"
    return "cháu" + ho


# a spouse of the person who is `term` to the other side: what the spouse is called (husband or wife of that relative)
_SPOUSE_OF = {
    ("chú", "wife"): "thím", ("bác", "wife"): "bác gái", ("cô", "husband"): "dượng", ("ông", "wife"): "bà",
    ("cụ ông", "wife"): "cụ bà", ("anh", "wife"): "chị dâu", ("chị", "husband"): "anh rể", ("em trai", "wife"): "em dâu",
    ("em gái", "husband"): "em rể", ("con", "wife"): "con dâu", ("con", "husband"): "con rể", ("cháu", "wife"): "cháu dâu",
    ("cháu", "husband"): "cháu rể", ("chắt", "wife"): "chắt dâu", ("chắt", "husband"): "chắt rể",
    ("cha", "wife"): "mẹ", ("anh họ", "wife"): "chị dâu họ", ("em họ", "wife"): "em dâu họ", ("chú họ", "wife"): "thím họ",
}
# the relative's term seen from the spouse's side: what the blood relative is to the spouse
_TO_SPOUSE = {
    ("em trai", "wife"): "em chồng", ("em gái", "wife"): "em chồng", ("anh", "wife"): "anh chồng", ("chị", "wife"): "chị chồng",
    ("em trai", "husband"): "em vợ", ("em gái", "husband"): "em vợ", ("anh", "husband"): "anh vợ", ("chị", "husband"): "chị vợ",
    ("cha", "wife"): "cha chồng", ("mẹ", "wife"): "mẹ chồng", ("cha", "husband"): "cha vợ", ("mẹ", "husband"): "mẹ vợ",
    ("con", "wife"): "con", ("con", "husband"): "con", ("cháu", "wife"): "cháu", ("cháu", "husband"): "cháu",
}


def _spouse_word(x: Member) -> str:
    return _by_gender(x, "chồng", "vợ", "vợ/chồng")


def _wife_or_husband(x: Member) -> str:
    return "husband" if x.gender == "male" else "wife"


def _path_up(layout: TreeLayout, member: Member) -> list[Member]:
    path = [member]
    seen = {member.id}
    while path[-1].parent_id is not None:
        parent = layout.by_id.get(path[-1].parent_id)
        if parent is None or parent.id in seen:
            break
        seen.add(parent.id)
        path.append(parent)
    return path


def relate(a: Member, b: Member, layout: TreeLayout) -> Relation:
    if a.id == b.id:
        return Relation("self", "chính người này", "chính người này", f"{a.full_name} và {b.full_name} là cùng một người.")
    partner_a = layout.partner_of.get(a.id)
    partner_b = layout.partner_of.get(b.id)
    if partner_a == b.id or partner_b == a.id:
        return Relation(
            "spouse", _spouse_word(a), _spouse_word(b), f"{a.full_name} là {_spouse_word(a)} của {b.full_name}.",
        )
    if b.mother_id == a.id or a.mother_id == b.id:
        mother, child = (a, b) if b.mother_id == a.id else (b, a)
        a_is, b_is = ("mẹ", "con") if mother is a else ("con", "mẹ")
        return Relation("blood", a_is, b_is, f"{a.full_name} là {a_is} của {b.full_name}.")

    anchor_a = layout.by_id[partner_a] if partner_a in layout.by_id else a
    anchor_b = layout.by_id[partner_b] if partner_b in layout.by_id else b
    path_a, path_b = _path_up(layout, anchor_a), _path_up(layout, anchor_b)
    index_b = {m.id: i for i, m in enumerate(path_b)}
    meeting = next(((i, index_b[m.id]) for i, m in enumerate(path_a) if m.id in index_b), None)
    if meeting is None:
        return Relation("none", sentence=f"Không tìm thấy quan hệ huyết thống giữa {a.full_name} và {b.full_name} trong cây.")
    da, db = meeting
    ancestor = path_a[da]
    ca = path_a[da - 1] if da > 0 else None
    cb = path_b[db - 1] if db > 0 else None
    term_ab = _blood_term(anchor_a, anchor_b, da, db, ca, cb)
    term_ba = _blood_term(anchor_b, anchor_a, db, da, cb, ca)
    anchored = anchor_a is not a or anchor_b is not b
    if not anchored:
        return Relation("blood", term_ab, term_ba, f"{a.full_name} là {term_ab} của {b.full_name}.", ancestor, da, db)

    # at least one of them is a spouse: describe through the partner(s)
    if anchor_a is not a and anchor_b is b:
        a_is = _SPOUSE_OF.get((term_ab, _wife_or_husband(a))) or f"{_spouse_word(a)} của {anchor_a.full_name} ({term_ab} của {b.full_name})"
        b_is = _TO_SPOUSE.get((term_ba, _wife_or_husband(a))) or f"{term_ba} của {anchor_a.full_name}"
        sentence = f"{a.full_name} là {a_is} của {b.full_name}."
    elif anchor_b is not b and anchor_a is a:
        b_is = _SPOUSE_OF.get((term_ba, _wife_or_husband(b))) or f"{_spouse_word(b)} của {anchor_b.full_name} ({term_ba} của {a.full_name})"
        a_is = _TO_SPOUSE.get((term_ab, _wife_or_husband(b))) or f"{term_ab} của {anchor_b.full_name}"
        sentence = f"{a.full_name} là {a_is} của {b.full_name}."
    else:
        a_is = f"{_spouse_word(a)} của {anchor_a.full_name}"
        b_is = f"{_spouse_word(b)} của {anchor_b.full_name}"
        sentence = f"{a.full_name} là {a_is}, {b.full_name} là {b_is}; {anchor_a.full_name} là {term_ab} của {anchor_b.full_name}."
    return Relation("in_law", a_is, b_is, sentence, ancestor, da, db)
