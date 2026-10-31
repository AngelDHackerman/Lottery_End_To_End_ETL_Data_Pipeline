"""The frames the suites run on: silver tables, prepared, and two derived from them.

GX checks one column at a time. Several expectations of DESIGN.md are about a draw instead
("20 numbers per Quiniela", "the extra is not among the 5 de Oro"), so each draw's shape is
measured here with pandas and GX validates the measurement (owner, UY-026 2a). Same for
``dq_flags``, a list column that GX cannot check against a set: it is unrolled, one row per
flag.

Dates go to the suites as ISO text. A ``datetime`` in a GX row condition does not survive the
suite's own serialization, and ISO text compares the same as the date it spells.
"""

from __future__ import annotations

import pandas as pd

from sorteos.uy import dq_flags as dq

KEY = ["country", "operator", "game", "draw_date"]

QUINIELA_VESPERTINA = "quiniela_vespertina"
QUINIELA_NOCTURNA = "quiniela_nocturna"
CINCO_DE_ORO = "5_de_oro"

#: game -> the ball types each of its draws must have. Written out rather than read from the
#: YAML: the gate checks the transform, and one shared mistake would pass both.
BALL_TYPES = {
    QUINIELA_VESPERTINA: ("quiniela", "tombola"),
    QUINIELA_NOCTURNA: ("quiniela", "tombola"),
    CINCO_DE_ORO: ("oro", "extra", "revancha"),
}

_SHAPE = ["count", "positions_ok", "ascending", "repeats", "clashes"]
_EMPTY_SHAPE = {"count": 0, "positions_ok": True, "ascending": True, "repeats": 0, "clashes": 0}


def draw_key(frame: pd.DataFrame) -> pd.Series:
    """``country|operator|game|draw_date``: one text value for the key of ``draws``."""
    text = [frame[column].astype(str) for column in KEY]
    return text[0].str.cat(text[1:], sep="|")


def draws(frame: pd.DataFrame) -> pd.DataFrame:
    """``draws`` plus the weekday (Monday is 0) and whether its number is out of sequence."""
    out = _dated(frame)
    out["weekday"] = pd.to_datetime(out["draw_date"]).dt.dayofweek
    out["out_of_sequence"] = frame["dq_flags"].map(
        lambda flags: dq.DRAW_NUMBER_OUT_OF_SEQUENCE in flags
    )
    return out


def draw_numbers(frame: pd.DataFrame) -> pd.DataFrame:
    """``draw_numbers`` plus the number as an integer and the key of its draw."""
    out = _dated(frame)
    out["value"] = pd.to_numeric(out["number"], errors="coerce")
    out["draw_key"] = draw_key(out)
    return out


def prizes(frame: pd.DataFrame) -> pd.DataFrame:
    """``prizes`` with the amount as a float (GX compares numbers) and the key of its draw."""
    out = _dated(frame)
    out["pool_amount"] = pd.to_numeric(out["pool_amount"], errors="coerce").astype(float)
    out["draw_key"] = draw_key(out)
    return out


def shapes(draws: pd.DataFrame, numbers: pd.DataFrame) -> pd.DataFrame:
    """One row per draw and ball type its game must have, with what was found.

    ``count`` is how many numbers; ``positions_ok`` that the positions are exactly 1..count;
    ``ascending`` that the values never go down in position order; ``repeats`` how many are
    repeated; ``clashes`` how many of the extra's numbers are also 5 de Oro numbers of the
    same draw (0 for the other ball types). A ball type with no numbers at all is a row with
    ``count`` 0, so a draw that lost one is still seen.
    """
    expected = pd.DataFrame(
        [(game, ball) for game, balls in BALL_TYPES.items() for ball in balls],
        columns=["game", "ball_type"],
    )
    rows = _dated(draws)[KEY].merge(expected, on="game")
    found = _measure(_dated(numbers))
    out = rows.merge(found, on=[*KEY, "ball_type"], how="left")
    for column, empty in _EMPTY_SHAPE.items():
        out[column] = out[column].fillna(empty).astype(type(empty))
    return out[[*KEY, "ball_type", *_SHAPE]]


def flags(draws: pd.DataFrame, prizes: pd.DataFrame) -> pd.DataFrame:
    """One row per flag set in ``draws`` or ``prizes``; ``flag`` reads ``<table>.<name>``."""
    parts = []
    for table, frame in (("draws", draws), ("prizes", prizes)):
        rows = _dated(frame)[[*KEY, "dq_flags"]].explode("dq_flags").dropna(subset=["dq_flags"])
        parts.append(rows.assign(flag=table + "." + rows["dq_flags"].astype(str)))
    out = pd.concat(parts, ignore_index=True)
    return out[[*KEY, "flag"]]


_GAP_DATES = (
    "previous_draw_date",
    "expected_date",
    "window_end",
    "next_draw_date",
    "calendar_event_date",
)


def draw_gaps(frame: pd.DataFrame) -> pd.DataFrame:
    """``draw_gaps`` plus what its dates must say about each other (D14): ``window_days`` from
    the expected date to the end of its window, whether the expected date is after the draw
    that set it, and whether the draw that finally came is after the window (or none came)."""
    out = frame.copy()
    dates = {c: pd.to_datetime(out[c]) for c in _GAP_DATES}
    out["window_days"] = (dates["window_end"] - dates["expected_date"]).dt.days
    out["expected_after_previous"] = dates["expected_date"] > dates["previous_draw_date"]
    out["next_after_window"] = dates["next_draw_date"].isna() | (
        dates["next_draw_date"] > dates["window_end"]
    )
    for column in _GAP_DATES:
        out[column] = dates[column].dt.strftime("%Y-%m-%d")
    return out


def _dated(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["draw_date"] = pd.to_datetime(out["draw_date"]).dt.strftime("%Y-%m-%d")
    return out


def _measure(numbers: pd.DataFrame) -> pd.DataFrame:
    group = [*KEY, "ball_type"]
    ordered = numbers.assign(value=pd.to_numeric(numbers["number"], errors="coerce"))
    ordered = ordered.sort_values([*group, "position"], kind="stable")
    by = ordered.groupby(group, sort=False)
    ordered["position_ok"] = ordered["position"] == by.cumcount() + 1
    ordered["step_ok"] = by["value"].diff().fillna(0) >= 0
    by = ordered.groupby(group, sort=False)
    out = pd.DataFrame(
        {
            "count": by.size(),
            "positions_ok": by["position_ok"].all(),
            "ascending": by["step_ok"].all(),
            "repeats": by.size() - by["number"].nunique(),
        }
    ).reset_index()

    oro = ordered.loc[ordered["ball_type"] == "oro", [*KEY, "number"]]
    extra = ordered.loc[ordered["ball_type"] == "extra", [*KEY, "number"]]
    clashes = extra.merge(oro, on=[*KEY, "number"]).groupby(KEY).size().rename("clashes")
    out = out.merge(clashes.reset_index().assign(ball_type="extra"), on=group, how="left")
    out["clashes"] = out["clashes"].fillna(0)
    return out
