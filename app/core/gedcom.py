"""GEDCOM 5.5.1 export of one tree: the format other genealogy programs (Ancestry, MyHeritage, Gramps, ...) read.

A pure function over plain rows, so it is tested without a database. Mapping from the patrilineal model of this app:

- every person row (blood relatives and the spouses who married in) is an INDI; the name is split the Vietnamese way, the first word is
  the family name (``Nguyễn Văn Một`` -> ``Văn Một /Nguyễn/``);
- each marriage is a FAM (the blood member and the spouse); the children whose mother is that spouse are its CHIL. Children whose mother
  is unknown, or who belong to a member without marriages, go into a FAM that has only that parent;
- a lunar date has no place in GEDCOM 5.5.1 (no lunar calendar escape), so only its year goes into DATE and the lunar day/month go into
  a NOTE; a day/month without a year is likewise kept as a NOTE;
- not carried: photos and documents (the backup has them), branches (chi/phái), sibling order other than the order of CHIL lines.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable
from typing import Any

MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
SEX = {"male": "M", "female": "F"}
LINE_LIMIT = 200  # GEDCOM allows 255 characters a line; leave room for the level and tag


def split_name(full_name: str) -> tuple[str, str]:
    """(given names, family name): the first word is the family name, a single word is a given name."""
    words = full_name.replace("/", " ").split()
    if len(words) <= 1:
        return (words[0] if words else "", "")
    return (" ".join(words[1:]), words[0])


def _text(value: str) -> str:
    return value.replace("@", "@@")


def _lines(level: int, tag: str, value: str | None = None) -> list[str]:
    """One GEDCOM line; a value with line breaks or longer than the limit continues on CONT / CONC lines."""
    if value is None or value == "":
        return [f"{level} {tag}"]
    out: list[str] = []
    for index, paragraph in enumerate(value.replace("\r\n", "\n").replace("\r", "\n").split("\n")):
        chunks = [paragraph[i : i + LINE_LIMIT] for i in range(0, len(paragraph), LINE_LIMIT)] or [""]
        for chunk_index, chunk in enumerate(chunks):
            text = _text(chunk)
            if index == 0 and chunk_index == 0:
                out.append(f"{level} {tag} {text}".rstrip())
            elif chunk_index == 0:
                out.append(f"{level + 1} CONT {text}".rstrip())
            else:
                out.append(f"{level + 1} CONC {text}")
    return out


def date_parts(
    year: int | None, month: int | None, day: int | None, *, lunar: bool, leap: bool
) -> tuple[str | None, str | None]:
    """(DATE value, NOTE): what a possibly partial, possibly lunar date becomes in GEDCOM."""
    if lunar:
        note = None
        if month is not None:
            note = f"Âm lịch: {day}/{month}" if day is not None else f"Âm lịch: tháng {month}"
            if leap:
                note += " (tháng nhuận)"
        return (str(year) if year is not None else None, note)
    if year is not None:
        parts = [str(year)]
        if month is not None:
            parts.insert(0, MONTHS[month - 1])
            if day is not None:
                parts.insert(0, str(day))
        return (" ".join(parts), None)
    if month is not None:
        return (None, f"Dương lịch: {day}/{month}" if day is not None else f"Dương lịch: tháng {month}")
    return (None, None)


def _event(tag: str, date: tuple[str | None, str | None], extra: Iterable[str] = ()) -> list[str]:
    value, note = date
    body = list(extra)
    if value is None and note is None and not body:
        return []
    out = _lines(1, tag)
    if value is not None:
        out += _lines(2, "DATE", value)
    if note is not None:
        out += _lines(2, "NOTE", note)
    return out + body


def _child_order(member: Any) -> tuple[bool, int, int]:
    return (member.birth_order is None, member.birth_order or 0, member.id)


def build_gedcom(
    *,
    tree_name: str,
    members: list[Any],
    marriages: list[Any],
    places: dict[int, Any],
    exported_at: datetime.datetime,
) -> str:
    """The whole file as text (UTF-8, LF line ends). ``members`` are ``Member`` rows, ``marriages`` ``Marriage`` rows."""
    by_id = {m.id: m for m in members}
    marriages = [x for x in marriages if x.member_id in by_id and x.spouse_id in by_id]
    spouse_ids = {x.spouse_id for x in marriages}
    marriages_of: dict[int, list[Any]] = {}
    for marriage in sorted(marriages, key=lambda x: x.id):
        marriages_of.setdefault(marriage.member_id, []).append(marriage)
    children_of: dict[int, list[Any]] = {}
    for member in members:
        if member.parent_id in by_id and member.id not in spouse_ids:
            children_of.setdefault(member.parent_id, []).append(member)
    for siblings in children_of.values():
        siblings.sort(key=_child_order)

    # families: (id, husband, wife, marriage row or None, children)
    families: list[dict[str, Any]] = []
    famc: dict[int, int] = {}  # child -> family number
    fams: dict[int, list[int]] = {}  # person -> families they are a spouse in
    for parent_id in sorted(set(marriages_of) | set(children_of)):
        parent = by_id[parent_id]
        kids = list(children_of.get(parent_id, []))
        groups: list[tuple[Any | None, list[Any]]] = []
        for marriage in marriages_of.get(parent_id, []):
            mine = [k for k in kids if k.mother_id == marriage.spouse_id]
            groups.append((marriage, mine))
            kids = [k for k in kids if k not in mine]
        if kids:  # mother unknown (or not a recorded spouse)
            groups.append((None, kids))
        for marriage, group in groups:
            spouse = by_id[marriage.spouse_id] if marriage is not None else None
            number = len(families) + 1
            husband, wife = (spouse, parent) if parent.gender == "female" else (parent, spouse)
            families.append({"n": number, "husband": husband, "wife": wife, "marriage": marriage, "children": group})
            for person in (parent, spouse):
                if person is not None:
                    fams.setdefault(person.id, []).append(number)
            for child in group:
                famc[child.id] = number

    out: list[str] = []
    out += ["0 HEAD", "1 SOUR GiaPha", "2 NAME Gia phả", "1 GEDC", "2 VERS 5.5.1", "2 FORM LINEAGE-LINKED"]
    out += ["1 CHAR UTF-8", "1 LANG Vietnamese"]
    day = exported_at.day
    out += [f"1 DATE {day} {MONTHS[exported_at.month - 1]} {exported_at.year}"]
    out += _lines(1, "NOTE", f"Gia phả: {tree_name}")

    for member in sorted(members, key=lambda m: m.id):
        given, family = split_name(member.full_name)
        out += [f"0 @I{member.id}@ INDI"]
        name_line = f"{given} /{family}/".strip() if given else f"/{family}/"
        out += _lines(1, "NAME", name_line)
        if given:
            out += _lines(2, "GIVN", given)
        if family:
            out += _lines(2, "SURN", family)
        if member.courtesy_name:
            out += _lines(2, "NICK", member.courtesy_name)
        out += _lines(1, "SEX", SEX.get(member.gender or "", "U"))
        out += _event(
            "BIRT",
            date_parts(member.birth_year, member.birth_month, member.birth_day, lunar=member.birth_is_lunar, leap=member.birth_leap_month),
        )
        out += _event(
            "DEAT",
            date_parts(member.death_year, member.death_month, member.death_day, lunar=member.death_is_lunar, leap=member.death_leap_month),
        )
        out += _burial(member, places.get(member.burial_place_id) if member.burial_place_id else None)
        if member.residence:
            out += _lines(1, "RESI") + _lines(2, "PLAC", member.residence)
        if member.hometown:
            out += _lines(1, "EVEN") + _lines(2, "TYPE", "Quê quán") + _lines(2, "PLAC", member.hometown)
        if member.title:
            out += _lines(1, "TITL", member.title)
        if member.phone:
            out += _lines(1, "PHON", member.phone)
        if member.email:
            out += _lines(1, "EMAIL", member.email)
        if member.notes:
            out += _lines(1, "NOTE", member.notes)
        if member.id in famc:
            out += [f"1 FAMC @F{famc[member.id]}@", f"2 PEDI {'adopted' if member.is_adopted else 'birth'}"]
        for number in fams.get(member.id, []):
            out += [f"1 FAMS @F{number}@"]

    for family in families:
        out += [f"0 @F{family['n']}@ FAM"]
        if family["husband"] is not None:
            out += [f"1 HUSB @I{family['husband'].id}@"]
        if family["wife"] is not None:
            out += [f"1 WIFE @I{family['wife'].id}@"]
        marriage = family["marriage"]
        if marriage is not None:
            out += _lines(1, "MARR")
            if marriage.marriage_year is not None:
                out += _lines(2, "DATE", str(marriage.marriage_year))
        for child in family["children"]:
            out += [f"1 CHIL @I{child.id}@"]
    out += ["0 TRLR"]
    return "\n".join(out) + "\n"


def _burial(member: Any, place: Any | None) -> list[str]:
    place_name = place.name if place is not None else member.burial_place
    latitude = member.burial_latitude if member.burial_latitude is not None else (place.latitude if place is not None else None)
    longitude = member.burial_longitude if member.burial_longitude is not None else (place.longitude if place is not None else None)
    notes = []
    if place is not None and member.burial_place and member.burial_place != place.name:
        notes.append(member.burial_place)
    if member.burial_plot:
        notes.append(f"Vị trí mộ: {member.burial_plot}")
    if member.burial_map_url:
        notes.append(f"Bản đồ: {member.burial_map_url}")
    if not (place_name or notes or latitude is not None):
        return []
    out = _lines(1, "BURI")
    if place_name:
        out += _lines(2, "PLAC", place_name)
        if latitude is not None and longitude is not None:
            out += _lines(3, "MAP") + _lines(4, "LATI", f"{'N' if latitude >= 0 else 'S'}{abs(latitude):.6f}")
            out += _lines(4, "LONG", f"{'E' if longitude >= 0 else 'W'}{abs(longitude):.6f}")
    if notes:
        out += _lines(2, "NOTE", "\n".join(notes))
    return out
