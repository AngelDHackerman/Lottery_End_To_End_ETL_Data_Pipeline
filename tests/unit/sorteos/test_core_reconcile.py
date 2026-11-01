"""UY-030: every weekday of a game's calendar, accounted for from the gap detector's view."""

from __future__ import annotations

import random
from datetime import date, timedelta

from sorteos.core import gaps
from sorteos.core import reconcile as rc
from sorteos.core.gaps import Draw

WED_SUN = ("wed", "sun")  # the 5 de Oro's calendar
MON_FRI = ("mon", "tue", "wed", "thu", "fri")  # the Vespertina's
LATER = date(2027, 1, 1)


def d(day: str) -> date:
    return date.fromisoformat(day)


def kinds(draws, weekdays=WED_SUN, events=(), today=LATER):
    return [(x.day.isoformat(), x.kind) for x in rc.account(draws, weekdays, events, today)]


def test_no_draws_nothing_to_account_for():
    assert rc.account([], WED_SUN, [], LATER) == []


def test_a_holiday_the_previous_draw_announced_past_is_skipped():
    # A Vespertina on Friday that announces Tuesday: Monday is a holiday.
    draws = [Draw(d("2026-10-09"), d("2026-10-13")), Draw(d("2026-10-13"), None)]
    assert kinds(draws, MON_FRI, today=d("2026-10-14")) == [
        ("2026-10-09", rc.ON_CALENDAR),
        ("2026-10-12", rc.SKIPPED),
        ("2026-10-13", rc.ON_CALENDAR),
    ]


def test_a_draw_moved_without_a_new_announcement_leaves_a_moved_day():
    # Announced Wednesday, drawn Thursday: within the window, a hit (D14 rule 2).
    draws = [Draw(d("2026-10-25"), d("2026-10-28")), Draw(d("2026-10-29"), None)]
    assert kinds(draws, today=d("2026-10-30")) == [
        ("2026-10-25", rc.ON_CALENDAR),
        ("2026-10-28", rc.MOVED),
        ("2026-10-29", rc.OFF_CALENDAR_MOVED),
    ]


def test_a_draw_announced_off_the_calendar_skips_the_calendar_day():
    # 2019-10-02: the 5 de Oro was moved to Friday the 4th, and the Sunday before said so.
    draws = [Draw(d("2019-09-29"), d("2019-10-04")), Draw(d("2019-10-04"), None)]
    assert kinds(draws, today=d("2019-10-05")) == [
        ("2019-09-29", rc.ON_CALENDAR),
        ("2019-10-02", rc.SKIPPED),
        ("2019-10-04", rc.OFF_CALENDAR_ANNOUNCED),
    ]


def test_the_days_of_a_gap_take_its_status_and_the_draw_after_it_is_other():
    # The 2019 AFAL strike: the 22nd announced the 25th, the next draw came on Tuesday 1-Oct.
    draws = [Draw(d("2019-09-22"), d("2019-09-25")), Draw(d("2019-10-01"), None)]
    assert kinds(draws, events=[d("2019-09-25")], today=d("2019-10-02")) == [
        ("2019-09-22", rc.ON_CALENDAR),
        ("2019-09-25", rc.GAP_EXPLAINED),
        ("2019-09-29", rc.GAP_EXPLAINED),
        ("2019-10-01", rc.OFF_CALENDAR_OTHER),
    ]
    assert kinds(draws, today=d("2019-10-02"))[1] == ("2019-09-25", rc.GAP_OPEN)


def test_an_early_draw_has_no_day_without_a_draw_before_it():
    # The 5 de Oro of 2012-06-17 announced the 21st and was drawn on Wednesday the 20th.
    draws = [Draw(d("2012-06-17"), d("2012-06-21")), Draw(d("2012-06-20"), None)]
    assert kinds(draws, today=d("2012-06-21")) == [
        ("2012-06-17", rc.ON_CALENDAR),
        ("2012-06-20", rc.ON_CALENDAR),
    ]


def test_a_first_draw_off_the_calendar_is_other():
    assert kinds([Draw(d("2026-10-29"), None)], today=d("2026-10-30")) == [
        ("2026-10-29", rc.OFF_CALENDAR_OTHER)
    ]


def test_days_after_the_last_draw_count_once_its_window_closed():
    draws = [Draw(d("2026-10-21"), d("2026-10-25"))]
    assert kinds(draws, today=d("2026-10-28")) == [("2026-10-21", rc.ON_CALENDAR)]
    assert kinds(draws, today=d("2026-10-29")) == [
        ("2026-10-21", rc.ON_CALENDAR),
        ("2026-10-25", rc.GAP_OPEN),
        ("2026-10-28", rc.GAP_OPEN),  # window_end: the last day the draw could still come
    ]


def test_month_counts_add_draws_and_calendar_days():
    draws = [Draw(d("2019-09-22"), d("2019-09-25")), Draw(d("2019-10-01"), d("2019-10-02"))]
    months = rc.month_counts(rc.account(draws, WED_SUN, [d("2019-09-25")], d("2019-10-02")))
    assert dict(months[(2019, 9)]) == {
        rc.ON_CALENDAR: 1,
        rc.GAP_EXPLAINED: 2,
        "draws": 1,
        "calendar": 3,
    }
    assert dict(months[(2019, 10)]) == {rc.OFF_CALENDAR_OTHER: 1, "draws": 1, "calendar": 0}


def test_every_calendar_weekday_is_accounted_for_once():
    # A random history: draws on most calendar days, some moved, some announced past a
    # holiday, a few missing. The kinds must cover each weekday exactly once.
    rng = random.Random(30)
    draws, day = [], d("2015-01-04")  # a Sunday
    while day < d("2017-12-31"):
        step = rng.choice([3, 4, 3, 4, 3, 4, 5, 7, 8, 11])
        announced = day + timedelta(days=step) if rng.random() < 0.9 else None
        draws.append(Draw(day, announced))
        day += timedelta(days=step + rng.choice([0, 0, 0, 0, 1, -1]))
        day = max(day, draws[-1].draw_date + timedelta(days=1))
    days = rc.account(draws, WED_SUN, [], LATER)

    assert len({x.day for x in days}) == len(days)
    assert [x.day for x in days if x.kind in rc.DRAW] == [x.draw_date for x in draws]
    months = rc.month_counts(days)
    assert sum(c["calendar"] for c in months.values()) == rc.calendar_weekdays(
        days[0].day, days[-1].day, WED_SUN
    )
    assert {x.kind for x in days} <= set(rc.KINDS)
    assert any(x.kind == rc.GAP_OPEN for x in days)  # the random history has holes


def test_calendar_weekdays_counts_from_the_dates_alone():
    assert rc.calendar_weekdays(d("2026-10-01"), d("2026-10-31"), WED_SUN) == 8
    assert rc.calendar_weekdays(d("2026-10-01"), d("2026-10-31"), MON_FRI) == 22
    assert rc.calendar_weekdays(d("2026-10-02"), d("2026-10-02"), WED_SUN) == 0


def test_the_kinds_come_from_the_same_expectations_as_draw_gaps():
    draws = [Draw(d("2019-09-22"), d("2019-09-25")), Draw(d("2019-10-01"), None)]
    (gap,) = gaps.expected_draws(draws, WED_SUN, [], d("2019-10-02"))
    days = rc.account(draws, WED_SUN, [], d("2019-10-02"))
    assert min(x.day for x in days if x.kind == rc.GAP_OPEN) == gap.expected_date
