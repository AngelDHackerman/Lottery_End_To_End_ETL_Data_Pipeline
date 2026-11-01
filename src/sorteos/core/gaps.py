"""The gap detector: did a draw that should have happened not happen? (DESIGN.md, D13-D15).

One pure function serves the backfill report and the incremental's alarm, so the two can
never disagree about a day. It takes one game's draws (``draw_date`` and the announced
``next_draw_date``), the weekdays its YAML declares and the dates of the ``calendar_events``
rows of that game, plus today, which it never reads from the clock. No requests, no files.

For each draw it expects the next one (D14):

1. On the date the draw announced, if it falls in (draw, draw + 14 days] (P10); otherwise on
   the next weekday of the game's calendar.
2. Within 3 days of that date, because the DNLQ moves a draw to the next day without changing
   the announcement.
3. A next draw *before* the expected date is early, not a gap: nothing is missing.
4. No draw in the window is a gap: ``explained`` when a ``calendar_events`` row of the game
   falls between the expected date and the draw that finally happened (D15), ``open`` if not.

The last draw's expectation counts only once its window has closed (``window_end`` before
today): until then the draw can still come. While no draw has come since, only an event in
the window itself explains the gap: a suspension a week later says nothing about why the
expected draw is missing, and must not hide it (UY-028.2).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from sorteos.core.config import WEEKDAYS

# P10: an announcement is believed up to 14 days after the draw that made it.
ANNOUNCEMENT_CAP = timedelta(days=14)
WINDOW = timedelta(days=3)

ANNOUNCEMENT = "announcement"
CALENDAR = "calendar"

HIT = "hit"
EARLY = "early"
GAP = "gap"

EXPLAINED = "explained"
OPEN = "open"


@dataclass(frozen=True)
class Draw:
    draw_date: date
    next_draw_date: date | None  # what the draw announced, as read (D14 rule 6)


@dataclass(frozen=True)
class Expectation:
    previous_draw_date: date
    expected_date: date
    expected_from: str  # ANNOUNCEMENT or CALENDAR
    window_end: date
    next_draw_date: date | None  # the draw that happened next; None if none yet
    outcome: str  # HIT, EARLY or GAP
    status: str | None  # EXPLAINED or OPEN for a GAP, None otherwise
    calendar_event_date: date | None  # the first event that explains a GAP


def believed(draw_date: date, announced: date | None) -> bool:
    """P10: the announcement is a date in (draw, draw + 14 days]. ``next_draw_implausible``
    marks the draws whose announcement this rejects."""
    return announced is not None and draw_date < announced <= draw_date + ANNOUNCEMENT_CAP


def next_weekday(after: date, weekdays: Collection[str]) -> date:
    wanted = {WEEKDAYS.index(w) for w in weekdays}
    if not wanted:
        raise ValueError("a calendar needs at least one weekday")
    day = after + timedelta(days=1)
    while day.weekday() not in wanted:
        day += timedelta(days=1)
    return day


def expectations(
    draws: Sequence[Draw], weekdays: Collection[str], events: Collection[date], today: date
) -> list[Expectation]:
    """One expectation per draw whose next draw happened or whose window closed, in order."""
    for before, after in zip(draws, draws[1:], strict=False):
        if not before.draw_date < after.draw_date:
            raise ValueError(f"draws out of order or repeated at {after.draw_date}")
    events = sorted(events)
    out = []
    for i, draw in enumerate(draws):
        if believed(draw.draw_date, draw.next_draw_date):
            expected, source = draw.next_draw_date, ANNOUNCEMENT
        else:
            expected, source = next_weekday(draw.draw_date, weekdays), CALENDAR
        window_end = expected + WINDOW
        happened = draws[i + 1].draw_date if i + 1 < len(draws) else None
        if happened is None and window_end >= today:
            continue  # the window is still open: the draw can still come
        if happened is not None and happened < expected:
            outcome = EARLY
        elif happened is not None and happened <= window_end:
            outcome = HIT
        else:
            outcome = GAP
        status = event = None
        if outcome == GAP:
            if happened is not None:
                event = next((e for e in events if expected <= e < happened), None)
            else:
                event = next((e for e in events if expected <= e <= window_end), None)
            status = EXPLAINED if event else OPEN
        out.append(
            Expectation(
                draw.draw_date, expected, source, window_end, happened, outcome, status, event
            )
        )
    return out


def expected_draws(
    draws: Sequence[Draw], weekdays: Collection[str], events: Collection[date], today: date
) -> list[Expectation]:
    """The gaps alone: the rows of ``draw_gaps`` for one game."""
    return [e for e in expectations(draws, weekdays, events, today) if e.outcome == GAP]
