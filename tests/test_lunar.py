"""The Vietnamese lunar calendar against dates everybody knows (Tết, Trung thu, leap months)."""

from datetime import date, timedelta

import pytest

from app.core.lunar import LunarDate, lunar_month_days, lunar_to_solar, solar_to_lunar

# (lunar year, solar date of mùng 1 Tết)
TET = [
    (2019, date(2019, 2, 5)),
    (2020, date(2020, 1, 25)),
    (2021, date(2021, 2, 12)),
    (2022, date(2022, 2, 1)),
    (2023, date(2023, 1, 22)),
    (2024, date(2024, 2, 10)),
    (2025, date(2025, 1, 29)),
    (2026, date(2026, 2, 17)),
    (2027, date(2027, 2, 6)),
    (2000, date(2000, 2, 5)),
    (1990, date(1990, 1, 27)),
    (1975, date(1975, 2, 11)),
]


@pytest.mark.parametrize("year,solar", TET)
def test_tet_dates(year, solar):
    assert solar_to_lunar(solar) == LunarDate(1, 1, year, False)
    assert lunar_to_solar(LunarDate(1, 1, year, False)) == solar


def test_other_well_known_dates():
    assert lunar_to_solar(LunarDate(15, 8, 2024, False)) == date(2024, 9, 17)  # Trung thu 2024
    assert lunar_to_solar(LunarDate(15, 8, 2023, False)) == date(2023, 9, 29)
    assert lunar_to_solar(LunarDate(15, 8, 2025, False)) == date(2025, 10, 6)
    assert lunar_to_solar(LunarDate(10, 3, 2024, False)) == date(2024, 4, 18)  # Giỗ tổ Hùng Vương 2024
    assert lunar_to_solar(LunarDate(10, 3, 2025, False)) == date(2025, 4, 7)
    assert lunar_to_solar(LunarDate(5, 5, 2024, False)) == date(2024, 6, 10)  # Tết Đoan ngọ
    assert solar_to_lunar(date(2000, 1, 1)) == LunarDate(25, 11, 1999, False)  # month 11 belongs to the previous lunar year
    assert solar_to_lunar(date(2024, 2, 9)) == LunarDate(30, 12, 2023, False)  # Giao thừa 2024 (December had 30 days)


def test_leap_months():
    assert lunar_to_solar(LunarDate(1, 4, 2020, True)) == date(2020, 5, 23)  # nhuận tháng 4 năm 2020
    assert solar_to_lunar(date(2020, 5, 23)) == LunarDate(1, 4, 2020, True)
    assert lunar_to_solar(LunarDate(1, 2, 2023, True)) == date(2023, 3, 22)  # nhuận tháng 2 năm 2023
    assert lunar_to_solar(LunarDate(1, 6, 2025, True)) == date(2025, 7, 25)  # nhuận tháng 6 năm 2025
    assert lunar_to_solar(LunarDate(1, 3, 2024, True)) is None  # 2024 has no leap month
    assert lunar_to_solar(LunarDate(1, 5, 2020, True)) is None  # the 2020 leap month is the 4th, not the 5th
    assert lunar_month_days(4, 2020, leap=True) in (29, 30)
    assert lunar_month_days(3, 2024, leap=True) is None


def test_every_day_round_trips_and_days_advance_one_at_a_time():
    day = date(1995, 1, 1)
    previous = solar_to_lunar(day - timedelta(days=1))
    while day < date(2046, 1, 1):
        lunar = solar_to_lunar(day)
        assert lunar_to_solar(lunar) == day, (day, lunar)
        # the next day is either the next day of the month or day 1 of the next month
        if lunar.day == 1:
            assert previous.day in (29, 30)
        else:
            assert lunar.day == previous.day + 1 and lunar[1:] == previous[1:], (day, lunar, previous)
        previous = lunar
        day += timedelta(days=1)


def test_months_have_29_or_30_days_and_a_year_has_12_or_13_months():
    for year in (2019, 2020, 2023, 2024, 2025, 2026):
        lengths = [lunar_month_days(m, year) for m in range(1, 13)]
        assert all(n in (29, 30) for n in lengths)
        total = sum(lengths) + sum(lunar_month_days(m, year, True) or 0 for m in range(1, 13))
        assert total in range(353, 356) or total in range(383, 386), (year, total)
