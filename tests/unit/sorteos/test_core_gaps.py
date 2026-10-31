"""D13-D15: expected_draws(), one game's draws against its announcements and its calendar."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from sorteos.core import gaps
from sorteos.core.gaps import Draw, Expectation

WED_SUN = ("wed", "sun")  # the 5 de Oro's calendar
# 2026-10: Wed 21, Sun 25, Wed 28, Sun 1-Nov.
WED, SUN, NEXT_WED, NEXT_SUN = (
    date(2026, 10, 21),
    date(2026, 10, 25),
    date(2026, 10, 28),
    date(2026, 11, 1),
)
LATER = date(2027, 1, 1)  # a today after every window


def d(day: str) -> date:
    return date.fromisoformat(day)


@pytest.mark.parametrize(
    ("announced", "believed"),
    [
        (None, False),
        (WED, False),  # the draw's own date
        (d("2026-10-20"), False),  # before the draw
        (d("2026-10-22"), True),
        (d("2026-11-04"), True),  # 14 days: Semana de Turismo 2020 and fin de año 2022 (P10)
        (d("2026-11-05"), False),  # 15 days
    ],
)
def test_an_announcement_is_believed_up_to_14_days_after_its_draw(announced, believed):
    assert gaps.believed(WED, announced) is believed


@pytest.mark.parametrize(
    ("after", "weekdays", "expected"),
    [
        (WED, WED_SUN, SUN),
        (d("2026-10-24"), WED_SUN, SUN),  # a Saturday
        (SUN, WED_SUN, NEXT_WED),
        (d("2026-10-23"), ("mon", "tue", "wed", "thu", "fri"), d("2026-10-26")),  # Fri -> Mon
    ],
)
def test_the_calendar_gives_the_next_weekday_strictly_after(after, weekdays, expected):
    assert gaps.next_weekday(after, weekdays) == expected


def test_a_calendar_without_weekdays_is_refused():
    with pytest.raises(ValueError, match="at least one weekday"):
        gaps.next_weekday(WED, ())


def one(draws, events=(), today=None) -> Expectation:
    """The single expectation of ``draws``. By default today is the day after the last draw,
    so that draw's own window is still open and adds nothing."""
    today = today or draws[-1].draw_date + timedelta(days=1)
    (expectation,) = gaps.expectations(draws, WED_SUN, events, today)
    return expectation


def test_the_announced_date_is_expected_and_met():
    e = one([Draw(WED, SUN), Draw(SUN, None)])
    assert e == Expectation(WED, SUN, gaps.ANNOUNCEMENT, d("2026-10-28"), SUN, gaps.HIT, None, None)


def test_a_draw_moved_up_to_3_days_is_still_a_hit():
    # 31 of the 34 misses of the 5 de Oro's announcement are a draw moved to the next day.
    assert one([Draw(WED, SUN), Draw(d("2026-10-28"), None)]).outcome == gaps.HIT
    assert one([Draw(WED, SUN), Draw(d("2026-10-29"), None)]).outcome == gaps.GAP


@pytest.mark.parametrize("announced", [None, d("2026-11-05"), WED])
def test_without_a_believable_announcement_the_calendar_decides(announced):
    e = one([Draw(WED, announced), Draw(SUN, None)])
    assert (e.expected_date, e.expected_from, e.outcome) == (SUN, gaps.CALENDAR, gaps.HIT)


def test_an_early_draw_is_not_a_gap():
    # The 5 de Oro of 2012-06-17 announced the 21st and was drawn on the 20th.
    e = one([Draw(d("2012-06-17"), d("2012-06-21")), Draw(d("2012-06-20"), None)])
    assert (e.outcome, e.status) == (gaps.EARLY, None)


def test_a_gap_with_an_event_of_the_game_is_explained():
    # The 2019 AFAL strike: expected 2019-09-25, drawn again on 2019-10-01.
    draws = [Draw(d("2019-09-22"), d("2019-09-25")), Draw(d("2019-10-01"), None)]
    events = [d("2019-09-26"), d("2019-09-25"), d("2019-10-01")]
    e = one(draws, events)
    assert (e.outcome, e.status, e.calendar_event_date) == (
        gaps.GAP,
        gaps.EXPLAINED,
        d("2019-09-25"),
    )
    assert e.window_end == d("2019-09-28")


@pytest.mark.parametrize(
    "event",
    [
        d("2019-09-24"),  # before the expected date
        d("2019-10-01"),  # the day the draw happened explains nothing that was missing
    ],
)
def test_an_event_outside_the_gap_leaves_it_open(event):
    draws = [Draw(d("2019-09-22"), d("2019-09-25")), Draw(d("2019-10-01"), None)]
    e = one(draws, [event])
    assert (e.outcome, e.status, e.calendar_event_date) == (gaps.GAP, gaps.OPEN, None)


def test_the_last_draw_waits_until_its_window_closes():
    draws = [Draw(WED, SUN)]
    assert gaps.expectations(draws, WED_SUN, [], today=d("2026-10-28")) == []  # window_end


def test_a_last_draw_whose_window_closed_is_an_open_gap_with_no_next_draw():
    e = one([Draw(WED, SUN)], today=d("2026-10-29"))
    assert (e.outcome, e.status, e.next_draw_date) == (gaps.GAP, gaps.OPEN, None)


def test_an_event_until_today_explains_a_gap_still_running():
    e = one([Draw(WED, SUN)], [SUN], today=d("2026-10-29"))
    assert (e.status, e.calendar_event_date) == (gaps.EXPLAINED, SUN)
    assert one([Draw(WED, SUN)], [d("2026-10-29")], today=d("2026-10-29")).status == gaps.OPEN


def test_one_expectation_per_draw_in_order_and_expected_draws_keeps_the_gaps():
    draws = [Draw(WED, SUN), Draw(SUN, NEXT_WED), Draw(d("2026-11-08"), None)]
    found = gaps.expectations(draws, WED_SUN, [], LATER)
    assert [(e.previous_draw_date, e.outcome) for e in found] == [
        (WED, gaps.HIT),
        (SUN, gaps.GAP),  # expected Wed 28, nothing until Sun 8-Nov
        (d("2026-11-08"), gaps.GAP),  # the last one: its calendar window closed long ago
    ]
    assert gaps.expected_draws(draws, WED_SUN, [], LATER) == [
        e for e in found if e.outcome == gaps.GAP
    ]
    assert NEXT_SUN not in [e.expected_date for e in found]


@pytest.mark.parametrize("second", [WED, d("2026-10-20")])
def test_draws_must_be_sorted_and_unique(second):
    with pytest.raises(ValueError, match="out of order or repeated at"):
        gaps.expectations([Draw(WED, None), Draw(second, None)], WED_SUN, [], LATER)


def test_no_draws_no_expectations():
    assert gaps.expected_draws([], WED_SUN, [], LATER) == []


def test_an_announced_skip_is_not_a_gap():
    # The 5 de Oro of 2006-08-23 announced "Domingo 3 de Setiembre de 2006", read since UY-022:
    # Sunday 27 was skipped on purpose, so nothing is missing. By the calendar alone it was the
    # one open gap DESIGN measured on 2026-10-25.
    draws = [Draw(d("2006-08-23"), d("2006-09-03")), Draw(d("2006-09-03"), d("2006-09-06"))]
    e = one(draws)
    assert (e.expected_date, e.expected_from, e.outcome) == (
        d("2006-09-03"),
        gaps.ANNOUNCEMENT,
        gaps.HIT,
    )
    assert one([Draw(d("2006-08-23"), None), draws[1]]).status == gaps.OPEN
