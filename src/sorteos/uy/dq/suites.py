"""Uruguay's silver suites (DESIGN.md, «Las suites (UY-026)»).

Each expectation cites its evidence, and each one was run against the silver of the whole
local bronze before it came in (PR-032): a gate that is red on arrival teaches everyone to
route around it. If one fails on real data, the expectation is what gets reviewed.

The static suites are committed as JSON under ``qa/uy/expectations/`` by
``scripts/uy_dq.py --sync-suites``, and a test fails if the two drift apart (PR-034). What
depends on this run, the 5 de Oro range from ``game_rules`` and the keys present in
``draws``, is built by :func:`run_time` and never committed (PR-049).

Two expectations come from ``master`` rather than from DESIGN's table (owner, UY-026 3a):
at least one row, so an empty directory cannot pass, and lineage that is never null.
"""

from __future__ import annotations

from pathlib import Path

import great_expectations as gx
from great_expectations import expectations as gxe
from great_expectations.core import ExpectationSuite
from great_expectations.expectations.row_conditions import Column

from sorteos.core import gaps, shapes
from sorteos.core.silver import LINEAGE
from sorteos.uy import dq_flags as dq
from sorteos.uy.dq.frames import (
    BALL_TYPES,
    CINCO_DE_ORO,
    KEY,
    QUINIELA_NOCTURNA,
    QUINIELA_VESPERTINA,
)

DRAWS = "uy_draws"
DRAW_NUMBERS = "uy_draw_numbers"
DRAW_SHAPES = "uy_draw_shapes"
PRIZES = "uy_prizes"
DQ_FLAGS = "uy_dq_flags"
DRAW_GAPS = "uy_draw_gaps"

GAME_RULES = Path(__file__).parents[1] / "reference" / "game_rules.csv"
#: The 5 de Oro's range_rule in its YAML. Every ball type of the game shares it.
RANGE_RULE = (CINCO_DE_ORO, "rango_numeros")

#: The first pozos PDF the site links, and so the first published draw number (UY-024).
FIRST_DRAW_NUMBER_DAY = "2016-06-01"
#: The 31 Tómbolas with a repeated number are all from 2006.
TOMBOLA_REPEATS_END = "2007-01-01"

SATURDAY, SUNDAY = 5, 6
_TIMES = ("started_local", "first_ball_local", "ended_local")
_TWO_DIGITS = ("tombola", "oro", "extra", "revancha")


def _at_least_one_row() -> gxe.Expectation:
    # An empty or misplaced silver directory would otherwise validate as green.
    return gxe.ExpectTableRowCountToBeBetween(min_value=1)


def _lineage() -> list[gxe.Expectation]:
    # Every row the UY writer produces carries all five, `run_id` included: a null one means
    # something wrote silver outside the pipeline (PR-045.1). No era condition is needed,
    # unlike master, because there is no silver from before lineage.
    return [gxe.ExpectColumnValuesToNotBeNull(column=f.name) for f in LINEAGE]


def _is(column: str, value) -> Column:
    return Column(column) == value


def build_draws() -> ExpectationSuite:
    five = _is("game", CINCO_DE_ORO)
    expectations = [
        _at_least_one_row(),
        # P1. The only key of the table: a draw written twice counts twice in every gold sum.
        gxe.ExpectCompoundColumnsToBeUnique(column_list=KEY),
        # The scope of v1; the Kini waits for UL2.
        gxe.ExpectColumnValuesToBeInSet(column="game", value_set=list(BALL_TYPES)),
        # Q2, verified over the whole history: no Quiniela on Sunday, no Vespertina on Saturday.
        gxe.ExpectColumnValuesToNotBeInSet(
            column="weekday", value_set=[SUNDAY], row_condition=_is("game", QUINIELA_NOCTURNA)
        ),
        gxe.ExpectColumnValuesToNotBeInSet(
            column="weekday",
            value_set=[SATURDAY, SUNDAY],
            row_condition=_is("game", QUINIELA_VESPERTINA),
        ),
        # C11: only the 5 de Oro has a draw number, ...
        gxe.ExpectColumnValuesToBeNull(
            column="draw_number", row_condition=Column("game").is_not_in([CINCO_DE_ORO])
        ),
        # ... unique without the 2017 run the site numbered wrong (UY-024), ...
        gxe.ExpectColumnValuesToBeUnique(
            column="draw_number", row_condition=five & _is("out_of_sequence", False)
        ),
        # ... and none before the first pozos PDF.
        gxe.ExpectColumnValuesToBeNull(
            column="draw_number", row_condition=Column("draw_date") < FIRST_DRAW_NUMBER_DAY
        ),
        # P2: the 5 de Oro's extract has no times.
        *(gxe.ExpectColumnValuesToBeNull(column=c, row_condition=five) for c in _TIMES),
        *_lineage(),
    ]
    return gx.ExpectationSuite(name=DRAWS, expectations=expectations)


def build_draw_numbers() -> ExpectationSuite:
    expectations = [
        _at_least_one_row(),
        # The ball types of each game; a missing one is caught by the shapes suite.
        *(
            gxe.ExpectColumnValuesToBeInSet(
                column="ball_type", value_set=list(balls), row_condition=_is("game", game)
            )
            for game, balls in BALL_TYPES.items()
        ),
        # D3: the Quiniela's numbers have 3 digits; the rest have 2 (the YAML, Q8).
        gxe.ExpectColumnValuesToMatchRegex(
            column="number", regex=r"^\d{3}$", row_condition=_is("ball_type", "quiniela")
        ),
        gxe.ExpectColumnValuesToMatchRegex(
            column="number",
            regex=r"^\d{2}$",
            row_condition=Column("ball_type").is_in(list(_TWO_DIGITS)),
        ),
        *_lineage(),
    ]
    return gx.ExpectationSuite(name=DRAW_NUMBERS, expectations=expectations)


def build_draw_shapes() -> ExpectationSuite:
    def count(ball: str, n: int) -> gxe.Expectation:
        return gxe.ExpectColumnValuesToBeBetween(
            column="count", min_value=n, max_value=n, row_condition=_is("ball_type", ball)
        )

    tombola = _is("ball_type", "tombola")
    expectations = [
        _at_least_one_row(),
        # D3, 10,877 extracts: 20 Quiniela numbers, in positions 1 to 20.
        count("quiniela", 20),
        gxe.ExpectColumnValuesToBeInSet(column="positions_ok", value_set=[True]),
        # The Tómbola: 20 numbers, in order, with no repeats since 2007. Or none: a Quiniela
        # published without its Tómbola is interpreted, an incomplete Tómbola is not (owner,
        # UY-022; once, the Vespertina of 2006-08-31).
        gxe.ExpectColumnValuesToBeInSet(column="count", value_set=[0, 20], row_condition=tombola),
        gxe.ExpectColumnValuesToBeInSet(
            column="ascending", value_set=[True], row_condition=tombola
        ),
        gxe.ExpectColumnValuesToBeBetween(
            column="repeats",
            min_value=0,
            max_value=0,
            row_condition=tombola & (Column("draw_date") >= TOMBOLA_REPEATS_END),
        ),
        # The 5 de Oro's YAML: 5 de Oro, 1 extra that is not among them, 5 de Revancha.
        count("oro", 5),
        count("extra", 1),
        count("revancha", 5),
        gxe.ExpectColumnValuesToBeBetween(
            column="clashes", min_value=0, max_value=0, row_condition=_is("ball_type", "extra")
        ),
    ]
    return gx.ExpectationSuite(name=DRAW_SHAPES, expectations=expectations)


def build_prizes() -> ExpectationSuite:
    status = Column("winners_status")
    expectations = [
        _at_least_one_row(),
        # D6: one currency, and an amount is null or not negative.
        gxe.ExpectColumnValuesToBeInSet(column="currency", value_set=["UYU"]),
        gxe.ExpectColumnValuesToBeBetween(column="pool_amount", min_value=0),
        # D7: 0 coupons if and only if no_winners, null if and only if unknown. With the
        # statuses closed, these four say both directions.
        gxe.ExpectColumnValuesToBeInSet(
            column="winners_status", value_set=["winners", "no_winners", "unknown"]
        ),
        gxe.ExpectColumnValuesToBeBetween(
            column="winning_coupons",
            min_value=0,
            max_value=0,
            row_condition=status == "no_winners",
        ),
        gxe.ExpectColumnValuesToBeBetween(
            column="winning_coupons", min_value=1, row_condition=status == "winners"
        ),
        gxe.ExpectColumnValuesToBeNull(column="winning_coupons", row_condition=status == "unknown"),
        gxe.ExpectColumnValuesToNotBeNull(
            column="winning_coupons", row_condition=status.is_not_in(["unknown"])
        ),
        *_lineage(),
    ]
    return gx.ExpectationSuite(name=PRIZES, expectations=expectations)


def build_dq_flags() -> ExpectationSuite:
    # D22: only the catalog's names, each on its own table.
    allowed = sorted(f"{table}.{flag}" for flag, table in dq.CATALOG.items())
    expectations = [gxe.ExpectColumnValuesToBeInSet(column="flag", value_set=allowed)]
    return gx.ExpectationSuite(name=DQ_FLAGS, expectations=expectations)


def build_draw_gaps() -> ExpectationSuite:
    explained = _is("status", gaps.EXPLAINED)
    expectations = [
        # No row count: a country could have no gaps. Uruguay has 4, all explained (UY-028.1),
        # and a missing table still fails, as TableEmpty.
        # One expectation per draw: two rows for the same draw would count one gap twice.
        gxe.ExpectCompoundColumnsToBeUnique(
            column_list=["country", "operator", "game", "previous_draw_date"]
        ),
        gxe.ExpectColumnValuesToBeInSet(column="game", value_set=list(BALL_TYPES)),
        # D13, D15: explained if and only if a calendar_events row says why.
        gxe.ExpectColumnValuesToBeInSet(column="status", value_set=[gaps.EXPLAINED, gaps.OPEN]),
        gxe.ExpectColumnValuesToNotBeNull(column="calendar_event_date", row_condition=explained),
        gxe.ExpectColumnValuesToBeNull(
            column="calendar_event_date", row_condition=_is("status", gaps.OPEN)
        ),
        gxe.ExpectColumnValuesToBeInSet(
            column="expected_from", value_set=[gaps.ANNOUNCEMENT, gaps.CALENDAR]
        ),
        # D14: the window is the expected date plus 3 days, and a gap is a draw that came
        # after it, or has not come yet.
        gxe.ExpectColumnValuesToBeInSet(column="window_days", value_set=[3]),
        gxe.ExpectColumnValuesToBeInSet(column="expected_after_previous", value_set=[True]),
        gxe.ExpectColumnValuesToBeInSet(column="next_after_window", value_set=[True]),
        *_lineage(),
    ]
    return gx.ExpectationSuite(name=DRAW_GAPS, expectations=expectations)


#: Suite -> builder: what is validated, synced to JSON and drift-tested.
BUILDERS = {
    DRAWS: build_draws,
    DRAW_NUMBERS: build_draw_numbers,
    DRAW_SHAPES: build_draw_shapes,
    PRIZES: build_prizes,
    DQ_FLAGS: build_dq_flags,
    DRAW_GAPS: build_draw_gaps,
}


def run_time(draw_keys) -> dict[str, list[gxe.Expectation]]:
    """This run's expectations, per suite: the ranges of ``game_rules`` and the parent keys.

    Every key of ``draw_numbers`` and ``prizes`` must be in ``draw_keys``, the keys of the
    ``draws`` loaded in this run (PR-049). A set rather than an anti-join, so the failure
    names the orphans.
    """
    present = sorted(set(draw_keys))
    ranges = shapes.load_ranges(GAME_RULES, [RANGE_RULE])[RANGE_RULE]
    in_range = []
    for r in ranges:
        condition = _is("game", CINCO_DE_ORO)
        if r.valid_from:
            condition = condition & (Column("draw_date") >= r.valid_from.isoformat())
        if r.valid_to:
            condition = condition & (Column("draw_date") <= r.valid_to.isoformat())
        in_range.append(
            gxe.ExpectColumnValuesToBeBetween(
                column="value", min_value=r.low, max_value=r.high, row_condition=condition
            )
        )

    def referential() -> gxe.Expectation:
        return gxe.ExpectColumnValuesToBeInSet(column="draw_key", value_set=present)

    return {DRAW_NUMBERS: [*in_range, referential()], PRIZES: [referential()]}
