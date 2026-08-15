"""Load Silver Parquet out of S3 and validate it against the PR-032 suites.

Design notes, because two obvious-looking alternatives were tried and rejected:

**Why the whole dataset is concatenated into one DataFrame instead of using a GX S3
datasource.** GX can point a ``pandas_s3`` datasource straight at the Silver prefix, and
the roadmap prompt asks for exactly that. But Silver is written one Parquet file per draw
(``silver/sorteos/year=YYYY/sorteo=NNNN/sorteos.parquet``), so each GX *batch* would be a
single file — and ``silver/sorteos`` files hold exactly **one row each**. Uniqueness of
``numero_sorteo`` is then trivially true in every batch and the expectation that matters
most in this project would pass forever while proving nothing. Uniqueness is a property of
the dataset, so the dataset is what gets validated.

**Why boto3 + BytesIO instead of ``pd.read_parquet("s3://...")``.** That form needs
``s3fs``, which pulls in ``aiobotocore`` and pins ``botocore`` hard. This module has to be
installable into whatever runtime PR-033 picks for the DQ job, so it stays on the boto3
that is already there.

The whole Silver layer is ~117k rows across 222 files; reading all of it costs a few
seconds and a few tens of MB, which is well inside any runtime we would use.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

import boto3
import pandas as pd

from loteria.dq.suites import PREMIOS_SUITE_NAME, SORTEOS_SUITE_NAME, SUITE_BUILDERS

logger = logging.getLogger(__name__)

SILVER_PREFIX_DEFAULT = "silver/"

#: Silver dataset directory -> the suite that describes it. Mirrors the prefixes the
#: transformer writes to (``SILVER_SORTEOS_PREFIX`` / ``SILVER_PREMIOS_PREFIX``).
DATASET_SUITES = {
    "sorteos": SORTEOS_SUITE_NAME,
    "premios": PREMIOS_SUITE_NAME,
}


class SilverDatasetEmpty(RuntimeError):
    """Raised when a Silver prefix contains no Parquet files at all.

    Distinct from a failed expectation on purpose. A zero-row frame would fail the
    ``expect_table_row_count_to_be_between`` expectation and be reported as "the data is
    bad", when the real situation is "there is no data here" — usually a wrong bucket, a
    wrong prefix, or a transformer that never ran. Those need a different response than a
    genuine quality failure, so they get a different signal.
    """


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------
def list_parquet_keys(bucket: str, prefix: str, s3_client=None) -> list[str]:
    """Every ``.parquet`` key under ``prefix``, sorted for a deterministic read order."""
    s3 = s3_client or boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    keys: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(
            obj["Key"] for obj in page.get("Contents", []) if obj["Key"].endswith(".parquet")
        )

    return sorted(keys)


def read_parquet_keys(bucket: str, keys: list[str], s3_client=None) -> pd.DataFrame:
    """Concatenate the given Parquet objects into one DataFrame.

    The Hive partition values (``year=``, ``sorteo=``) live in the key, not inside the file,
    so they are absent from the result. None of the expectations reference them — the
    partition is metadata about *where* a row is stored, and the transformer already derives
    it from ``fecha_sorteo`` (see PR-030's schema test), so validating it here would be
    checking the same value twice rather than checking the data.
    """
    s3 = s3_client or boto3.client("s3")

    frames = []
    for key in keys:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        frames.append(pd.read_parquet(io.BytesIO(body)))

    return pd.concat(frames, ignore_index=True)


def load_silver_dataset(
    bucket: str,
    dataset: str,
    silver_prefix: str = SILVER_PREFIX_DEFAULT,
    s3_client=None,
) -> tuple[pd.DataFrame, list[str]]:
    """Read every Parquet file of one Silver dataset. Returns ``(frame, keys)``.

    The keys come back with the frame so that callers can report how many files were read
    without paying for a second ``list_objects_v2`` pass over the prefix.
    """
    s3 = s3_client or boto3.client("s3")
    prefix = f"{silver_prefix}{dataset}/"
    keys = list_parquet_keys(bucket, prefix, s3_client=s3)

    if not keys:
        raise SilverDatasetEmpty(f"No Parquet files under s3://{bucket}/{prefix}")

    df = read_parquet_keys(bucket, keys, s3_client=s3)
    logger.info(
        "Loaded Silver dataset",
        extra={"dataset": dataset, "files": len(keys), "rows": len(df), "bucket": bucket},
    )
    return df, keys


# --------------------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------------------
@dataclass
class ExpectationOutcome:
    """One expectation's verdict, flattened out of the GX result object."""

    expectation: str
    column: str | None
    success: bool
    unexpected_count: int | None
    unexpected_percent: float | None
    #: A few offending values, for the failure message. Never the full list — a broken
    #: column can produce 100k of them and this ends up in a CloudWatch log line.
    partial_unexpected: list = field(default_factory=list)


@dataclass
class SuiteOutcome:
    suite: str
    dataset: str
    rows: int
    files: int
    results: list[ExpectationOutcome]

    @property
    def success(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def failures(self) -> list[ExpectationOutcome]:
        return [r for r in self.results if not r.success]


@dataclass
class DQReport:
    suites: list[SuiteOutcome]

    @property
    def success(self) -> bool:
        # `all([])` is True, so an empty report would claim success. Validating nothing is
        # not the same as validating successfully.
        return bool(self.suites) and all(s.success for s in self.suites)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "suites": [
                {
                    "suite": s.suite,
                    "dataset": s.dataset,
                    "rows": s.rows,
                    "files": s.files,
                    "success": s.success,
                    "results": [
                        {
                            "expectation": r.expectation,
                            "column": r.column,
                            "success": r.success,
                            "unexpected_count": r.unexpected_count,
                            "unexpected_percent": r.unexpected_percent,
                            "partial_unexpected": r.partial_unexpected,
                        }
                        for r in s.results
                    ],
                }
                for s in self.suites
            ],
        }


# --------------------------------------------------------------------------------------
# Making GX quiet enough to run unattended
# --------------------------------------------------------------------------------------
# Both of these exist because in PR-033 this runs as a batch job whose only output channel
# is a log stream. They are applied in the runner rather than in the CLI so that every
# caller — the CLI, the Glue job, the tests — gets the same behaviour.
def quiet_gx() -> None:
    """Drop GX's own INFO chatter to WARNING.

    ``logging.getLogger("great_expectations").setLevel(...)`` is NOT enough: GX sets an
    explicit level on individual submodule loggers (e.g.
    ``great_expectations.data_context.types.base``), and an explicit child level wins over
    an inherited parent one. So every already-registered ``great_expectations*`` logger has
    to be set directly, after the import that registers them.
    """
    for name, logger_obj in logging.Logger.manager.loggerDict.items():
        if name.startswith("great_expectations") and isinstance(logger_obj, logging.Logger):
            logger_obj.setLevel(logging.WARNING)


def _disable_progress_bars(context) -> None:
    """Turn off the tqdm "Calculating Metrics" bar.

    tqdm redraws by writing carriage returns to stderr. On a terminal that animates; in
    CloudWatch Logs every redraw is retained, so a single validation lands as one enormous
    unreadable line. There is no env var for this — it is a data-context setting.
    """
    from great_expectations.data_context.types.base import ProgressBarsConfig

    context.variables.progress_bars = ProgressBarsConfig(globally=False)


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------
def validate_dataframe(dataset: str, df: pd.DataFrame, files: int = 0) -> SuiteOutcome:
    """Run one dataset's suite against an already-loaded DataFrame.

    Uses an **ephemeral** GX context. The committed context under ``qa/great_expectations/``
    is a review artifact synced by ``scripts/run_dq.py --sync-suites``; validation itself
    writes nothing, so it works in a read-only container and leaves no uncommitted GX state
    behind on a developer's machine.
    """
    # Imported here, not at module scope: `great_expectations` costs several seconds to
    # import (it drags in scipy, altair and pydantic), and `load_silver_dataset` is useful
    # on its own — notably to the tests, which import this module far more often than they
    # validate with it.
    import great_expectations as gx

    quiet_gx()

    suite_name = DATASET_SUITES[dataset]
    suite = SUITE_BUILDERS[suite_name]()

    context = gx.get_context(mode="ephemeral")
    _disable_progress_bars(context)
    context.suites.add(suite)

    source = context.data_sources.add_pandas(name=f"silver_{dataset}")
    asset = source.add_dataframe_asset(name=dataset)
    batch_definition = asset.add_batch_definition_whole_dataframe("all")

    validation_definition = context.validation_definitions.add(
        gx.ValidationDefinition(name=f"vd_{suite_name}", data=batch_definition, suite=suite)
    )

    raw = validation_definition.run(batch_parameters={"dataframe": df})

    results = []
    for item in raw.results:
        config = item.expectation_config
        detail = item.result or {}
        results.append(
            ExpectationOutcome(
                expectation=config.type,
                # Pair expectations key on column_A instead of column.
                column=config.kwargs.get("column") or config.kwargs.get("column_A"),
                success=bool(item.success),
                unexpected_count=detail.get("unexpected_count"),
                unexpected_percent=detail.get("unexpected_percent"),
                partial_unexpected=list(detail.get("partial_unexpected_list") or [])[:10],
            )
        )

    outcome = SuiteOutcome(
        suite=suite_name, dataset=dataset, rows=len(df), files=files, results=results
    )
    logger.info(
        "Suite validated",
        extra={
            "suite": suite_name,
            "dataset": dataset,
            "rows": len(df),
            "success": outcome.success,
            "failed_expectations": len(outcome.failures),
        },
    )
    return outcome


def run_dq(
    bucket: str,
    datasets: list[str] | None = None,
    silver_prefix: str = SILVER_PREFIX_DEFAULT,
    s3_client=None,
) -> DQReport:
    """Load and validate each requested Silver dataset.

    Every dataset is validated even after one fails — a DQ run that stops at the first
    failure makes you fix, re-run and wait to discover the second one, and in PR-033 each
    re-run is a Glue job start.
    """
    s3 = s3_client or boto3.client("s3")
    selected = datasets or list(DATASET_SUITES)

    unknown = set(selected) - set(DATASET_SUITES)
    if unknown:
        raise ValueError(f"Unknown dataset(s): {sorted(unknown)}. Known: {sorted(DATASET_SUITES)}")

    outcomes = []
    for dataset in selected:
        df, keys = load_silver_dataset(bucket, dataset, silver_prefix=silver_prefix, s3_client=s3)
        outcomes.append(validate_dataframe(dataset, df, files=len(keys)))

    return DQReport(suites=outcomes)
