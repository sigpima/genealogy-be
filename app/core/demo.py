"""The fake family behind the /guest demo (design: docs/superpowers/specs/2026-11-24-guest-demo-design.md).

`build_demo_family` is pure: a seeded random generator, no database, no clock, so every run gives the same family.
Nothing here comes from real data: names are put together from short lists of common Vietnamese names and the
hometowns are invented villages.
"""

import random
from dataclasses import dataclass
from itertools import count

DEMO_SLUG = "demo"
DEMO_NAME = "Họ Demo (dữ liệu giả)"
DEMO_SEED = 20261124

HOMETOWNS = (
    "Làng Đông, Nam Định",
    "Làng Thượng, Hà Nam",
    "Xã Phú Lâm, Thái Bình",
    "Làng Hạ, Ninh Bình",
)

_SURNAME = "Lê"
_MALE_MIDDLE = ("Văn", "Đình", "Quang", "Hữu", "Minh", "Xuân", "Công", "Bá")
_MALE_GIVEN = (
    "An", "Bình", "Cường", "Dũng", "Đạt", "Hải", "Hiếu", "Hoàng", "Hùng", "Khánh", "Kiên", "Lâm", "Long", "Nam", "Nghĩa",
    "Phong", "Phúc", "Quân", "Sơn", "Tài", "Thắng", "Thành", "Thiện", "Tuấn", "Trung", "Trường", "Việt", "Vinh", "Vũ", "Duy",
)
_FEMALE_GIVEN = (
    "Anh", "Bích", "Chi", "Dung", "Hà", "Hạnh", "Hoa", "Hồng", "Huệ", "Lan", "Liên", "Linh", "Loan", "Mai", "Ngân",
    "Nhung", "Oanh", "Phương", "Thảo", "Thu", "Thủy", "Trang", "Tuyết", "Vân", "Yến", "Xuân", "Quỳnh", "Ngọc", "Lệ", "Hiền",
)
_FEMALE_MIDDLE = ("Thị", "Ngọc", "Kim", "Bích")
_SPOUSE_SURNAMES = ("Nguyễn", "Trần", "Phạm", "Vũ", "Đỗ", "Hoàng", "Bùi", "Đặng", "Ngô", "Dương")

# children per son, by the son's generation (generation 1 is fixed in `_generate`; generation 6 has no children)
_CHILDREN = {2: (2, 3, 3, 4), 3: (2, 3, 3), 4: (1, 2, 3), 5: (1, 2, 2)}
_DAUGHTER_SHARE = 0.4
_ROOT_BIRTH_YEAR = 1845
_LAST_DEATH_YEAR = 2025  # nobody in the fake family dies after this: generations 5-6 are the living ones
_BLOOD_RANGE = (90, 130)
_GENERATIONS = 6


@dataclass(frozen=True)
class DemoPerson:
    """`partner_key is None` = a blood member; otherwise the spouse of that blood member (no parent of their own)."""

    key: int
    name: str
    gender: str  # "male" | "female"
    generation: int
    parent_key: int | None
    partner_key: int | None
    birth_year: int
    birth_month: int | None
    birth_day: int | None
    death_year: int | None
    death_month: int | None
    death_day: int | None  # a lunar date: the giỗ
    hometown: str | None
    marriage_year: int | None


@dataclass(frozen=True)
class DemoArticle:
    title: str
    kind: str
    body: str
    status: str  # "published" | "draft"
    pinned: bool


@dataclass(frozen=True)
class DemoTimeline:
    year: int
    month: int | None
    day: int | None
    title: str
    body: str | None


@dataclass(frozen=True)
class DemoWord:
    generation: int
    word: str
    meaning: str | None


@dataclass(frozen=True)
class DemoEvent:
    title: str
    description: str | None
    kind: str
    calendar: str  # "solar" | "lunar"
    month: int
    day: int
    repeats_yearly: bool


@dataclass(frozen=True)
class DemoBranch:
    head_key: int
    name: str
    color: str


@dataclass(frozen=True)
class DemoFamily:
    people: list[DemoPerson]
    branches: list[DemoBranch]
    articles: list[DemoArticle]
    timeline: list[DemoTimeline]
    poem: list[DemoWord]
    events: list[DemoEvent]


_ARTICLES = [
    DemoArticle(
        "Nguồn gốc dòng họ",
        "origin",
        "Họ Lê ở làng Đông lập nghiệp từ cuối thế kỷ XIX.\n\nĐây là **bài viết mẫu** của bản demo; mọi tên người và địa danh đều là giả.",
        "published",
        False,
    ),
    DemoArticle(
        "Tộc ước",
        "precepts",
        "- Hiếu thảo với ông bà cha mẹ.\n- Anh em hòa thuận, giúp nhau lúc hoạn nạn.\n- Giữ gìn nhà thờ họ và mộ phần tổ tiên.",
        "published",
        True,
    ),
    DemoArticle(
        "Giỗ Tổ hằng năm",
        "event",
        "Cả họ về nhà thờ làm lễ giỗ Tổ vào ngày mùng 10 tháng 3 âm lịch.",
        "published",
        False,
    ),
    DemoArticle("Bản nháp chưa đăng", "other", "Bài này còn đang viết, khách không thấy.", "draft", False),
]

_TIMELINE = [
    DemoTimeline(1845, None, None, "Cụ tổ chào đời", "Khởi đầu của dòng họ trong bản demo."),
    DemoTimeline(1880, 4, None, "Dựng nhà thờ họ", None),
    DemoTimeline(1925, None, None, "Lập gia phả đầu tiên", "Ghi tên các đời từ cụ tổ."),
    DemoTimeline(1954, 10, None, "Cả họ trở về quê cũ", None),
    DemoTimeline(1990, None, None, "Trùng tu nhà thờ họ", None),
    DemoTimeline(2010, 3, 10, "Giỗ Tổ lần đầu có mặt đủ bốn chi", None),
]

_POEM = [
    DemoWord(1, "Đức", "đạo đức, nền tảng của gia đình"),
    DemoWord(2, "Nghĩa", "tình nghĩa anh em"),
    DemoWord(3, "Hiếu", "hiếu thảo với cha mẹ"),
    DemoWord(4, "Trung", "trung thực, trung hậu"),
    DemoWord(5, "Tín", "giữ chữ tín"),
    DemoWord(6, "Hòa", "hòa thuận trong họ"),
]

_EVENTS = [
    DemoEvent("Giỗ Tổ", "Lễ giỗ Tổ của cả họ tại nhà thờ.", "memorial", "lunar", 3, 10, True),
    DemoEvent("Họp mặt đầu năm", "Cả họ gặp nhau đầu năm mới.", "gathering", "solar", 1, 2, True),
    DemoEvent("Lễ Thanh minh", "Thăm và dọn mộ tổ tiên.", "memorial", "lunar", 3, 3, True),
]

_BRANCHES = (("Chi nhất", "#c0392b"), ("Chi nhì", "#2980b9"), ("Chi ba", "#27ae60"))


class _TooLarge(Exception):
    """This random draw grew past the size the demo should have; the caller draws again."""


class _Names:
    """Unique full names (the data-health page flags the same name and birth year twice)."""

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self._used: set[str] = set()

    def _unique(self, make) -> str:
        for _ in range(500):
            name = make()
            if name not in self._used:
                self._used.add(name)
                return name
        raise RuntimeError("ran out of fake names")

    def male(self) -> str:
        return self._unique(lambda: f"{_SURNAME} {self._rng.choice(_MALE_MIDDLE)} {self._rng.choice(_MALE_GIVEN)}")

    def daughter(self) -> str:
        return self._unique(lambda: f"{_SURNAME} {self._rng.choice(_FEMALE_MIDDLE)} {self._rng.choice(_FEMALE_GIVEN)}")

    def wife(self) -> str:
        return self._unique(lambda: f"{self._rng.choice(_SPOUSE_SURNAMES)} {self._rng.choice(_FEMALE_MIDDLE)} {self._rng.choice(_FEMALE_GIVEN)}")


def _death(rng: random.Random, generation: int, birth_year: int) -> tuple[int | None, int | None, int | None]:
    """Generations 1-4 have died (with a lunar day and month for the giỗ); 5-6 are alive."""
    if generation > 4:
        return None, None, None
    year = min(birth_year + rng.randint(55, 88), _LAST_DEATH_YEAR)
    return year, rng.randint(1, 12), rng.randint(1, 29)


def _generate(rng: random.Random) -> list[DemoPerson]:
    names = _Names(rng)
    keys = count(1)
    people: list[DemoPerson] = []

    def add(name: str, gender: str, generation: int, birth_year: int, *, parent_key=None, partner_key=None, marriage_year=None) -> DemoPerson:
        death_year, death_month, death_day = _death(rng, generation, birth_year)
        person = DemoPerson(
            key=next(keys),
            name=name,
            gender=gender,
            generation=generation,
            parent_key=parent_key,
            partner_key=partner_key,
            birth_year=birth_year,
            birth_month=rng.randint(1, 12),
            birth_day=rng.randint(1, 28),
            death_year=death_year,
            death_month=death_month,
            death_day=death_day,
            hometown=rng.choice(HOMETOWNS) if partner_key is None and rng.random() < 0.5 else None,
            marriage_year=marriage_year,
        )
        people.append(person)
        if partner_key is None and sum(1 for p in people if p.partner_key is None) > _BLOOD_RANGE[1]:
            raise _TooLarge
        return person

    def marry(son: DemoPerson) -> None:
        add(
            names.wife(),
            "female",
            son.generation,
            son.birth_year - rng.randint(0, 5),
            partner_key=son.key,
            marriage_year=son.birth_year + rng.randint(20, 30),
        )

    root = add(names.male(), "male", 1, _ROOT_BIRTH_YEAR)
    marry(root)
    queue = [root]
    while queue:
        father = queue.pop(0)
        if father.generation == _GENERATIONS:
            continue
        if father.generation == 1:
            genders = ["male", "male", "male", "female"]  # three sons head the three branches
        else:
            total = rng.choice(_CHILDREN[father.generation])
            genders = ["female" if rng.random() < _DAUGHTER_SHARE else "male" for _ in range(total)]
            if "male" not in genders:
                genders[0] = "male"  # a line never ends with only daughters (they have no children in this tree)
        for index, gender in enumerate(genders):
            birth_year = father.birth_year + 22 + index * rng.randint(1, 3) + rng.randint(0, 4)
            name = names.male() if gender == "male" else names.daughter()
            child = add(name, gender, father.generation + 1, birth_year, parent_key=father.key)
            if gender == "male":
                queue.append(child)
                if child.generation < _GENERATIONS:
                    marry(child)
    return people


def build_demo_family(seed: int = DEMO_SEED) -> DemoFamily:
    """The same family for the same seed. The random draw is repeated (deterministically) until its size is in range."""
    for attempt in range(1000):
        try:
            people = _generate(random.Random(f"{seed}:{attempt}"))
        except _TooLarge:
            continue
        blood = [p for p in people if p.partner_key is None]
        if _BLOOD_RANGE[0] <= len(blood) <= _BLOOD_RANGE[1] and max(p.generation for p in blood) == _GENERATIONS:
            break
    else:  # pragma: no cover - the parameters above make this practically unreachable
        raise RuntimeError("could not generate a demo family of the expected size")
    root_sons = [p for p in people if p.parent_key == people[0].key and p.gender == "male"][:3]
    branches = [DemoBranch(son.key, name, color) for son, (name, color) in zip(root_sons, _BRANCHES, strict=True)]
    return DemoFamily(people, branches, list(_ARTICLES), list(_TIMELINE), list(_POEM), list(_EVENTS))
