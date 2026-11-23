"""A draw's numbers against the shape its game declares (DESIGN.md, D21).

The parsers already check how many numbers each ball type has and how many digits each one
has. This checks the rest of what the YAML says: the range, which depends on the date and
comes from ``game_rules`` (PR-049: never a constant), no repeats, a ball type that cannot
share a number with another (``not_in``) and the published order. A draw that breaks any of
them cannot be interpreted and goes to quarantine whole.

The one exception is a ball type the caller names in ``flagged_repeats``: its repeats are a
``dq_flag`` of the country's catalog, not a reason for quarantine.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sorteos.core.config import Numbers

_RANGE = re.compile(r"(\d+)-(\d+)")


@dataclass(frozen=True)
class Range:
    low: int
    high: int
    valid_from: date | None  # None: since the game began
    valid_to: date | None  # None: still in force

    def covers(self, day: date) -> bool:
        return (self.valid_from is None or self.valid_from <= day) and (
            self.valid_to is None or day <= self.valid_to
        )


def load_ranges(
    path: Path, rules: Collection[tuple[str, str]]
) -> dict[tuple[str, str], list[Range]]:
    """The ``(game, rule)`` pairs of ``rules`` from ``game_rules.csv``, as ``low-high``."""
    out: dict[tuple[str, str], list[Range]] = {pair: [] for pair in rules}
    with open(path, encoding="utf-8", newline="") as fh:
        for line, row in enumerate(csv.DictReader(fh), start=2):
            pair = (row["game"], row["rule"])
            if pair not in out:
                continue
            match = _RANGE.fullmatch(row["value"].strip())
            if not match:
                raise ValueError(f"{path.name}:{line}: {row['value']!r} is not a range low-high")
            out[pair].append(
                Range(
                    int(match[1]),
                    int(match[2]),
                    date.fromisoformat(row["valid_from"]) if row["valid_from"] else None,
                    date.fromisoformat(row["valid_to"]) if row["valid_to"] else None,
                )
            )
    return out


def problems(
    game: str,
    day: date,
    shapes: Mapping[str, Numbers],
    numbers: Mapping[str, Sequence[str]],
    ranges: Mapping[tuple[str, str], Sequence[Range]],
    flagged_repeats: Collection[str] = (),
) -> list[str]:
    """What does not fit, one text per problem; empty when the draw fits its shape.

    ``numbers`` maps each ball type to its numbers in position order. A ball type with no
    numbers is not checked: whether it should be there is the parser's call.
    """
    out = []
    for ball_type, published in numbers.items():
        spec = shapes[ball_type]
        if not published:
            continue
        if spec.order == "sorted" and list(published) != sorted(published):
            out.append(f"{ball_type} is not sorted: {list(published)}")
        if spec.repeats is False and ball_type not in flagged_repeats:
            if len(set(published)) != len(published):
                out.append(f"{ball_type} repeats a number: {list(published)}")
        for other in spec.not_in:
            shared = sorted(set(published) & set(numbers.get(other, ())))
            if shared:
                out.append(f"{ball_type} {shared} is also in {other}")
        if spec.range_rule:
            covering = [r for r in ranges.get((game, spec.range_rule), ()) if r.covers(day)]
            if len(covering) != 1:
                out.append(f"{len(covering)} {spec.range_rule} rows of {game} cover {day}")
                continue
            (rng,) = covering
            outside = [n for n in published if not rng.low <= int(n) <= rng.high]
            if outside:
                out.append(f"{ball_type} {outside} outside {rng.low:02d}-{rng.high:02d}")
    return out
