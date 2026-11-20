from datetime import date

import pytest

from handover.dates import find_dates

WED_4_MAR = date(2026, 3, 4)  # a Wednesday
FRI_22_MAY = date(2026, 5, 22)  # a Friday


def one(text, base):
    found = find_dates(text, base)
    assert len(found) == 1, found
    return found[0].value


@pytest.mark.parametrize("text,expected", [
    ("done by Friday", date(2026, 3, 6)),
    ("Thursday's site visit is off", date(2026, 3, 5)),
    ("by Wednesday", date(2026, 3, 11)),  # same weekday means next week, not today
    ("this Friday", date(2026, 3, 6)),
    ("next Monday", date(2026, 3, 9)),
    ("next Friday", date(2026, 3, 13)),  # the Friday of next week, not in two days
    ("last Friday", date(2026, 2, 27)),
    ("It's final. Sent it on Friday.", date(2026, 2, 27)),
])
def test_weekdays_resolve_against_message_date(text, expected):
    assert one(text, WED_4_MAR) == expected


def test_next_monday_said_on_friday_is_three_days_later():
    assert one("Lessons learned call next Monday?", FRI_22_MAY) == date(2026, 5, 25)


@pytest.mark.parametrize("text,expected", [
    ("the 14th", date(2026, 3, 14)),
    ("final by the 2nd", date(2026, 4, 2)),  # the 2nd already passed this month
    ("the 4th", date(2026, 3, 4)),  # today counts
    ("sorry, I meant the 18th", date(2026, 3, 18)),
    ("Thursday the 21st", date(2026, 3, 21)),
])
def test_day_of_month_is_next_occurrence(text, expected):
    assert one(text, WED_4_MAR) == expected


def test_ordinal_followed_by_a_noun_is_not_a_date():
    assert find_dates("Coffee machine on the 2nd floor is broken", WED_4_MAR) == []
    assert find_dates("the 3rd round of payments", WED_4_MAR) == []


@pytest.mark.parametrize("text,expected", [
    ("end of day tomorrow", date(2026, 3, 5)),
    ("by tomorrow noon", date(2026, 3, 5)),
    ("tomorrow", date(2026, 3, 5)),
    ("by end of day", date(2026, 3, 4)),
    ("today", date(2026, 3, 4)),
    ("should finish by end of the week", date(2026, 3, 6)),
    ("end of the month", date(2026, 3, 31)),
    ("in two weeks", date(2026, 3, 18)),
    ("in 3 days", date(2026, 3, 7)),
    ("within a week", date(2026, 3, 11)),
    ("in 5 working days", date(2026, 3, 11)),
])
def test_relative_expressions(text, expected):
    assert one(text, WED_4_MAR) == expected


def test_end_of_day_with_weekday_takes_the_weekday():
    assert one("by end of day Tuesday", FRI_22_MAY) == date(2026, 5, 26)


def test_relative_to_another_event_is_not_resolved():
    # "two weeks of the survey starting" is anchored to the survey, not the message
    assert find_dates("within two weeks of the survey starting", WED_4_MAR) == []


@pytest.mark.parametrize("text,expected", [
    ("14 March", date(2026, 3, 14)),
    ("March 14", date(2026, 3, 14)),
    ("14th of March", date(2026, 3, 14)),
    ("Thursday 12 March, 10:00", date(2026, 3, 12)),
    ("2026-04-10", date(2026, 4, 10)),
    ("10/04", date(2026, 4, 10)),
    ("31 March", date(2026, 3, 31)),
    ("Distribution date is 14 May.", date(2026, 5, 14)),
])
def test_explicit_dates(text, expected):
    assert one(text, WED_4_MAR) == expected


def test_explicit_date_long_past_rolls_to_next_year():
    assert one("10 January", date(2026, 11, 20)) == date(2027, 1, 10)


def test_weekday_with_ordinal_is_one_mention():
    found = find_dates("Racking now Wednesday the 11th.", date(2026, 3, 9))
    assert [m.value for m in found] == [date(2026, 3, 11)]


def test_several_mentions_in_order():
    found = find_dates("The count will finish Monday instead of today.", date(2026, 3, 13))
    assert [m.value for m in found] == [date(2026, 3, 16), date(2026, 3, 13)]


def test_weekday_before_numeric_date_is_one_mention():
    assert [m.value for m in find_dates("due Fri 10/04", WED_4_MAR)] == [date(2026, 4, 10)]


def test_weekday_with_a_time_is_still_the_weekday():
    assert [m.value for m in find_dates("call Monday 10am", WED_4_MAR)] == [date(2026, 3, 9)]


def test_may_without_a_day_is_not_a_date():
    assert find_dates("we may need more trucks", WED_4_MAR) == []
