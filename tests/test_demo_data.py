"""The fake family behind the /guest demo (see app/core/demo.py). The generator is pure, but tests/conftest.py rebuilds the test
database for every test file, so even this one needs `docker compose up -d --wait db-test` and must not run beside another pytest."""

import dataclasses

from app.core.demo import DEMO_SEED, HOMETOWNS, DemoPerson, build_demo_family


def _blood(family):
    return [p for p in family.people if p.partner_key is None]


def test_build_is_deterministic():
    assert build_demo_family(DEMO_SEED) == build_demo_family(DEMO_SEED)
    assert [p.name for p in build_demo_family(1).people] != [p.name for p in build_demo_family(2).people]


def test_shape_matches_the_spec():
    family = build_demo_family()
    blood = _blood(family)
    assert 90 <= len(blood) <= 130
    assert max(p.generation for p in blood) == 6
    assert len([p for p in blood if p.parent_key is None]) == 1

    by_key = {p.key: p for p in blood}
    assert len(family.branches) == 3
    assert all(by_key[b.head_key].generation == 2 for b in family.branches)

    assert len(family.articles) == 4
    assert [a.status for a in family.articles].count("draft") == 1
    assert any(a.kind == "precepts" for a in family.articles)
    assert len(family.poem) == 6
    assert len(family.timeline) >= 5
    assert len(family.events) >= 3
    assert all(e.repeats_yearly for e in family.events)  # a one-off event would expire and leave the demo calendar empty


def test_nothing_personal():
    fields = {f.name for f in dataclasses.fields(DemoPerson)}
    assert not {"phone", "email", "avatar_url", "residence", "notes"} & fields
    assert {p.hometown for p in build_demo_family().people if p.hometown} <= set(HOMETOWNS)


def test_ages_are_plausible():
    family = build_demo_family()
    by_key = {p.key: p for p in family.people}
    for person in family.people:
        if person.parent_key is not None:
            father = by_key[person.parent_key]
            assert 18 <= person.birth_year - father.birth_year <= 45, person.name
        if person.death_year is not None:
            assert 0 < person.death_year - person.birth_year <= 95, person.name
        if person.partner_key is None:
            if person.generation <= 4:
                assert person.death_year is not None and person.death_month and person.death_day, person.name
            if person.generation >= 5:
                assert person.death_year is None, person.name


def test_spouses_are_opposite_gender_and_same_generation():
    family = build_demo_family()
    by_key = {p.key: p for p in family.people}
    spouses = [p for p in family.people if p.partner_key is not None]
    assert spouses
    for spouse in spouses:
        partner = by_key[spouse.partner_key]
        assert partner.partner_key is None
        assert spouse.gender != partner.gender
        assert spouse.generation == partner.generation
        assert spouse.parent_key is None
        assert spouse.marriage_year >= max(spouse.birth_year, partner.birth_year) + 16


def test_keys_are_unique_and_parents_come_first():
    family = build_demo_family()
    keys = [p.key for p in family.people]
    assert len(keys) == len(set(keys))
    seen = set()
    for person in family.people:
        for ref in (person.parent_key, person.partner_key):
            assert ref is None or ref in seen, person.name
        seen.add(person.key)


def test_children_are_born_after_the_marriage():
    family = build_demo_family()
    marriage_year = {p.partner_key: p.marriage_year for p in family.people if p.partner_key is not None}
    for person in family.people:
        if person.parent_key in marriage_year:
            assert person.birth_year >= marriage_year[person.parent_key], person.name
