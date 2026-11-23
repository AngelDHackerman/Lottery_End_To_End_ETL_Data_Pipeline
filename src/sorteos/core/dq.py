"""Validate silver tables against Great Expectations suites (DESIGN.md, D20 and D21).

The country decides what the suites say; this decides how they run. It reads the tables a
``core.silver`` writer left on disk, runs each suite against one whole frame and reports
every expectation, so a failure names the suite, the expectation and the column, the way
``NotifyDQFailure`` does in ``master``.

**One frame per table, never one batch per file.** Silver is a Parquet file per partition,
and uniqueness checked file by file is true by construction: the gate would pass forever and
prove nothing (PR-032).

**Python is the source of truth for a suite.** :func:`suite_json` renders one for git, so a
reviewer can read the contract without running anything, and a test compares the committed
file with the code (PR-034). Expectations that need this run's data (a reference table, the
keys of a parent table) are passed as ``extra`` and never committed (PR-049).

``great_expectations`` is imported inside the functions that need it: it costs seconds to
import, and loading a table is useful without it. This module must also run on Glue 5.0,
which is Python 3.11.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

from sorteos.core.silver import Table

logger = logging.getLogger(__name__)

#: How many offending values a failure carries. A broken column can produce hundreds of
#: thousands, and the report ends up in one log line.
SAMPLE = 10


class TableEmpty(RuntimeError):
    """A table has no Parquet file at all. Validating nothing is not validating."""


def load(root: Path, table: Table) -> pd.DataFrame:
    """Every partition of ``table`` under ``root`` as one frame, path columns included.

    The partition columns come back with the types of the table's schema. Left to pyarrow
    they would be dictionary columns (pandas categoricals), whose comparisons in a row
    condition do not behave like a plain column's.
    """
    path = root / table.name
    files = sorted(path.rglob("*.parquet")) if path.is_dir() else []
    if not files:
        raise TableEmpty(f"{table.name}: no Parquet files under {path}")
    fields = [table.schema.field(name) for name in table.partition]
    if table.year_of:
        fields.append(pa.field("year", pa.int32()))
    partitioning = ds.partitioning(pa.schema(fields), flavor="hive")
    data = ds.dataset(path, format="parquet", partitioning=partitioning).to_table()
    return data.to_pandas()


@dataclass
class Outcome:
    """One expectation's verdict, flattened out of the GX result."""

    expectation: str
    column: str | None
    success: bool
    unexpected_count: int | None
    sample: list = field(default_factory=list)
    error: str | None = None


@dataclass
class SuiteResult:
    suite: str
    rows: int
    outcomes: list[Outcome]

    @property
    def success(self) -> bool:
        return all(o.success for o in self.outcomes)

    @property
    def failures(self) -> list[Outcome]:
        return [o for o in self.outcomes if not o.success]


@dataclass
class Report:
    results: list[SuiteResult]

    @property
    def success(self) -> bool:
        # `all([])` is True: a report that validated nothing must not read as green.
        return bool(self.results) and all(r.success for r in self.results)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "suites": [
                {
                    "suite": r.suite,
                    "rows": r.rows,
                    "success": r.success,
                    "outcomes": [o.__dict__ for o in r.outcomes],
                }
                for r in self.results
            ],
        }

    def text(self) -> str:
        lines = []
        for r in self.results:
            mark = "ok" if r.success else "FAILED"
            lines.append(f"{r.suite}: {mark} ({len(r.outcomes)} expectations, {r.rows} rows)")
            for o in r.failures:
                detail = o.error or f"{o.unexpected_count} unexpected, e.g. {o.sample}"
                lines.append(f"  - {o.expectation} on {o.column}: {detail}")
        lines.append("PASSED" if self.success else "FAILED")
        return "\n".join(lines)


def quiet_gx() -> None:
    """GX's own INFO chatter down to WARNING.

    Setting the ``great_expectations`` logger is not enough: GX gives some submodule loggers
    an explicit level, and an explicit level on a child wins over its parent's.
    """
    for name, item in logging.Logger.manager.loggerDict.items():
        if name.startswith("great_expectations") and isinstance(item, logging.Logger):
            item.setLevel(logging.WARNING)


def validate(suite, frame: pd.DataFrame, extra: Iterable = ()) -> SuiteResult:
    """Run ``suite`` (plus this run's ``extra`` expectations) against ``frame``.

    An ephemeral context: validating writes nothing, so it runs in a read-only container
    and leaves no GX state behind.
    """
    import great_expectations as gx
    from great_expectations.data_context.types.base import ProgressBarsConfig

    quiet_gx()
    # Rebuilt through the constructor: `add_expectation` needs an ambient data context.
    suite = gx.ExpectationSuite(name=suite.name, expectations=[*suite.expectations, *extra])
    context = gx.get_context(mode="ephemeral")
    # tqdm redraws with carriage returns, and a log stream keeps every redraw.
    context.variables.progress_bars = ProgressBarsConfig(globally=False)
    context.suites.add(suite)
    asset = context.data_sources.add_pandas(name=suite.name).add_dataframe_asset(name="frame")
    definition = context.validation_definitions.add(
        gx.ValidationDefinition(
            name=suite.name,
            data=asset.add_batch_definition_whole_dataframe("all"),
            suite=suite,
        )
    )
    raw = definition.run(batch_parameters={"dataframe": frame})

    outcomes = []
    for item in raw.results:
        kwargs = item.expectation_config.kwargs
        detail = item.result or {}
        error = _error(item.exception_info)
        outcomes.append(
            Outcome(
                expectation=item.expectation_config.type,
                column=kwargs.get("column") or ",".join(kwargs.get("column_list") or []) or None,
                success=bool(item.success) and not error,
                unexpected_count=detail.get("unexpected_count"),
                sample=_plain(detail.get("partial_unexpected_list") or [])[:SAMPLE],
                error=error,
            )
        )
    result = SuiteResult(suite=suite.name, rows=len(frame), outcomes=outcomes)
    logger.info(
        "suite validated",
        extra={"suite": suite.name, "rows": len(frame), "failed": len(result.failures)},
    )
    return result


def suite_json(suite) -> str:
    """The suite as committed to git: sorted, without the ids GX mints on every build.

    GX gives the suite and every expectation a fresh random id each time. Left in, one
    changed expectation would rewrite every line of the file.
    """
    data = json.loads(json.dumps(suite.to_json_dict(), default=str))
    data.pop("id", None)
    for expectation in data["expectations"]:
        expectation.pop("id", None)
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def sync(builders: Mapping[str, Callable[[], object]], directory: Path) -> list[Path]:
    """Write one ``<suite>.json`` per builder into ``directory`` and return the paths."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, build in builders.items():
        path = directory / f"{name}.json"
        path.write_text(suite_json(build()), encoding="utf-8")
        written.append(path)
    return written


def _error(info) -> str | None:
    """The first exception message in a result, if it raised.

    GX puts it at the top for some failures and, for a metric that raised, one level down,
    keyed by the metric's id.
    """
    if not isinstance(info, dict):
        return None
    if info.get("raised_exception") or info.get("exception_message"):
        return info.get("exception_message") or "raised"
    for value in info.values():
        if isinstance(value, dict) and value.get("exception_message"):
            return value["exception_message"]
    return None


def _plain(values: list) -> list:
    """GX hands back numpy scalars and dates, which a JSON report cannot carry."""
    out = []
    for v in values:
        v = v.item() if hasattr(v, "item") else v
        out.append(v if isinstance(v, str | int | float | bool | None) else str(v))
    return out
