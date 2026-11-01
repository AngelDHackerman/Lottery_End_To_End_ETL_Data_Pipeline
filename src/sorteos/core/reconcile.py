"""Every day of a game's calendar, accounted for (UY-030; DESIGN.md, D13-D15).

A month never has as many draws as its calendar has weekdays: the operator skips holidays,
moves a draw a day or two, and once in a while suspends one. This module says why, day by
day, from the same expectations the gap detector uses (``gaps.expectations``), so the
reconciliation report and ``draw_gaps`` can never disagree. No requests, no files.

Between one draw and the next, each weekday of the calendar without a draw is:

- ``skipped``: before the date the draw announced. The operator said there would be none.
- ``moved``: on or after the expected date, and the next draw came within its window (D14
  rule 2): the draw moved without the announcement changing.
- ``gap_explained`` / ``gap_open``: in a gap of ``draw_gaps``, by the gap's status.

And each draw is ``on_calendar`` or, on a weekday its calendar does not have:

- ``off_calendar_announced``: on the date the previous draw announced.
- ``off_calendar_moved``: a hit within the window, without the announcement saying so.
- ``off_calendar_other``: the first draw after a gap, or an early one.

The first draw has no previous one, so it is ``on_calendar`` or ``off_calendar_other``. Days
after the last draw count only once its window has closed, as in the gap detector. A month's
draws are then its calendar weekdays, minus the days without a draw, plus the off-calendar
draws, and :func:`calendar_weekdays` counts those weekdays without this module's help.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sorteos.core import gaps
from sorteos.core.config import WEEKDAYS

SKIPPED = "skipped"
MOVED = "moved"
GAP_EXPLAINED = "gap_explained"
GAP_OPEN = "gap_open"
NO_DRAW = (SKIPPED, MOVED, GAP_EXPLAINED, GAP_OPEN)

ON_CALENDAR = "on_calendar"
OFF_CALENDAR_ANNOUNCED = "off_calendar_announced"
OFF_CALENDAR_MOVED = "off_calendar_moved"
OFF_CALENDAR_OTHER = "off_calendar_other"
DRAW = (ON_CALENDAR, OFF_CALENDAR_ANNOUNCED, OFF_CALENDAR_MOVED, OFF_CALENDAR_OTHER)

KINDS = (*DRAW, *NO_DRAW)


@dataclass(frozen=True)
class Day:
    day: date
    kind: str


def account(
    draws: Sequence[gaps.Draw], weekdays: Collection[str], events: Collection[date], today: date
) -> list[Day]:
    """Every draw and every calendar weekday without one, in order, with its kind."""
    if not draws:
        return []
    wanted = {WEEKDAYS.index(w) for w in weekdays}
    first = draws[0].draw_date
    out = [Day(first, ON_CALENDAR if first.weekday() in wanted else OFF_CALENDAR_OTHER)]
    for e in gaps.expectations(draws, weekdays, events, today):
        until = e.next_draw_date or e.window_end + timedelta(days=1)
        day = e.previous_draw_date + timedelta(days=1)
        while day < until:
            if day.weekday() in wanted:
                out.append(Day(day, _no_draw(e, day)))
            day += timedelta(days=1)
        if e.next_draw_date is not None:
            out.append(Day(e.next_draw_date, _draw(e, wanted)))
    return out


def _no_draw(e: gaps.Expectation, day: date) -> str:
    if day < e.expected_date:
        return SKIPPED  # only an announcement puts the expected date past a calendar weekday
    if e.outcome == gaps.HIT:
        return MOVED
    return GAP_EXPLAINED if e.status == gaps.EXPLAINED else GAP_OPEN


def _draw(e: gaps.Expectation, wanted: set[int]) -> str:
    if e.next_draw_date.weekday() in wanted:
        return ON_CALENDAR
    if e.expected_from == gaps.ANNOUNCEMENT and e.next_draw_date == e.expected_date:
        return OFF_CALENDAR_ANNOUNCED
    if e.outcome == gaps.HIT:
        return OFF_CALENDAR_MOVED
    return OFF_CALENDAR_OTHER


def month_counts(days: Sequence[Day]) -> dict[tuple[int, int], Counter]:
    """Per (year, month): each kind, plus ``draws`` and ``calendar`` (the weekdays of the
    calendar that were accounted for)."""
    months: dict[tuple[int, int], Counter] = {}
    for d in days:
        months.setdefault((d.day.year, d.day.month), Counter())[d.kind] += 1
    for c in months.values():
        c["draws"] = sum(c[k] for k in DRAW)
        c["calendar"] = c[ON_CALENDAR] + sum(c[k] for k in NO_DRAW)
    return months


def calendar_weekdays(first: date, last: date, weekdays: Collection[str]) -> int:
    """The weekdays of the calendar in [first, last], counted from the dates alone."""
    wanted = {WEEKDAYS.index(w) for w in weekdays}
    return sum(
        (first + timedelta(days=i)).weekday() in wanted for i in range((last - first).days + 1)
    )
