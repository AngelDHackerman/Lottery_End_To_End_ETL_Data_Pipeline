"""The quarantine store for input the parser could not use (PR-044.2, fault E).

**The defect this closes.** When the parser met something it did not understand it logged
and moved on, and the row was gone — nothing recorded what it was, why it was dropped, or
which sorteo it came from. Silent loss is the worst failure mode a pipeline has, because
every downstream number still looks plausible: a gold `total_premios` short by four rows is
indistinguishable from a draw that had four fewer prizes.

PR-044.1 made the loss *visible* (counted and logged). This makes it *inspectable*.

**What gets stored, and what deliberately does not.** PR-044.1 measured the whole archive —
118 draws, 145,680 body lines — and found that **6.50% of every body is rejected, of which
99.99% are section headings** (`CENTENARES`, `DOS MIL`, …). Storing those would write ~9,500
rows of structural noise per draw, 1.1M across the archive, and make
``SELECT reason, count(*)`` useless. So:

* ``section_header`` — counted by PR-044.1, **never stored**. It is structure, not loss.
* ``orphan_vendor_line`` — stored. Never observed in the archive; it is the shape the body
  takes if the site reorders its blocks.
* ``unrecognised`` — stored. **One occurrence in the entire archive.**
* ``malformed_header`` / ``unexpected_key`` — stored. File-level, see below.

**This is not a dead-letter queue.** There is deliberately no replay path. The point is that
a human reads it and decides whether the parser or the source changed; an automatic retry
would turn "the site changed" into "the site changed, silently, every week".

**Nothing here may fail the run.** Every entry point swallows its own exceptions and reports
them, because the whole feature exists to stop one odd line from costing a week of
ingestion — and a quarantine writer that raises would do exactly that, while looking like
diligence.
"""

from __future__ import annotations

import io
import logging

import boto3
import pandas as pd

from loteria.common.lineage import PARSER_VERSION, utc_now

logger = logging.getLogger(__name__)

QUARANTINE_PREFIX_DEFAULT = "quarantine/"

#: File-level reason codes. The line-level ones live in ``loteria.parser.parser`` next to the
#: code that assigns them; these belong here because nothing in the parser is in a position
#: to know that a whole *file* was unusable.
#:
#: The header did not parse — PR-035.1's defect C. Until PR-044.2 this raised out of
#: ``process_header`` and **aborted the entire batch**, so one draw with an odd header was a
#: full weekly outage rather than one skipped record.
REJECT_MALFORMED_HEADER = "malformed_header"

#: The raw key did not match ``raw/year=YYYY/sorteo=NNNN/…``. Previously a ``logger.warning``
#: and a ``continue``, which is the same silent-loss shape one level up.
REJECT_UNEXPECTED_KEY = "unexpected_key"

#: The columns of a quarantine Parquet. Fixed and explicit because PR-044.2 registers this
#: prefix as a Glue table defined in **Terraform**, not inferred by a crawler — the two have
#: to agree, and a crawler that cannot evolve a schema (see PR-045.1) is a bad place to put
#: that agreement.
#: ⚠️ ``dataset``, ``year`` and ``sorteo`` are NOT here: they are the Hive **partition keys**,
#: carried by the S3 path. Glue rejects a table whose column list and partition keys overlap,
#: so writing them into the Parquet as well would make the table undefinable — and it would
#: also defeat partition pruning, which is the only reason to lay the prefix out this way.
#: Self-description is not lost: ``source_key`` is the full ``raw/year=…/sorteo=…`` key, so a
#: single file read straight out of S3 still says what it belongs to.
QUARANTINE_COLUMNS = (
    "reason",
    "line",
    "position",
    "source_key",
    "run_id",
    "parser_version",
    "quarantined_at",
)


def _s3():
    return boto3.client("s3")


def _typed_frame(rows: list[dict]) -> pd.DataFrame:
    """The rows as a frame whose Parquet types match what Terraform declares (PR-045.2).

    **Why this is not just ``pd.DataFrame(rows)``.** ``run_id`` is ``None`` for any write
    that did not come from a pipeline run — deliberately, see ``lineage.run_id_from_env`` —
    and pandas types an all-``None`` column as ``object``, which pyarrow writes to Parquet as
    the **Null** type rather than as a string. The catalog declares ``run_id string``, so
    such a file is a type mismatch at query time, in a table whose entire purpose is to be
    read after something went wrong. The failure would be perfectly hidden until then:
    quarantine's normal state is empty, so nothing exercises the write.

    ``line`` gets the same treatment for the same reason — a reject list that happened to
    carry only ``None`` lines would do it too — and the two integer columns are pinned to
    ``int64`` to match the ``bigint`` in Terraform. Athena widens INT to BIGINT and has no
    supported path back, so ``int`` over 64-bit data is the mismatch that cannot be read.
    """
    frame = pd.DataFrame(rows, columns=list(QUARANTINE_COLUMNS))
    for column in ("reason", "line", "source_key", "run_id"):
        frame[column] = frame[column].astype("string")
    for column in ("position", "parser_version"):
        frame[column] = frame[column].astype("int64")
    return frame


def quarantine_key(dataset: str, year, numero_sorteo, run_id: str | None) -> str:
    """Hive-partitioned so Athena can prune, and so one draw's rejects stay together.

    ``run=`` is the last element rather than a partition: a sorteo is normally quarantined
    once, but a reprocessing would otherwise overwrite the earlier evidence with the later
    one — and the earlier one is the record of what the parser used to do.
    """
    suffix = (run_id or "unknown").replace("/", "_")
    return (
        f"{QUARANTINE_PREFIX_DEFAULT}dataset={dataset}/year={year}/"
        f"sorteo={numero_sorteo}/{suffix}.parquet"
    )


def build_rows(
    rejects: list[dict],
    *,
    source_key: str,
    run_id: str | None,
) -> list[dict]:
    """Turn parser rejects into quarantine rows, dropping the ones that are structure.

    Returns ``[]`` when nothing is worth storing, which is the normal case: the archive
    baseline is one storable reject in 145,680 lines.
    """
    from loteria.parser.parser import REJECT_SECTION_HEADER

    now = utc_now()
    return [
        {
            "reason": r["reason"],
            "line": r["line"],
            "position": r["position"],
            "source_key": source_key,
            "run_id": run_id,
            "parser_version": PARSER_VERSION,
            "quarantined_at": now,
        }
        for r in rejects
        if r["reason"] != REJECT_SECTION_HEADER
    ]


def write(
    bucket: str,
    rows: list[dict],
    *,
    dataset: str,
    year,
    numero_sorteo,
    run_id: str | None,
    s3_client=None,
) -> int:
    """Persist quarantine rows as Parquet. Returns how many were written; never raises.

    **The swallowed exception is the feature.** A quarantine that can fail the run turns one
    odd footer line into a missed week of ingestion — the exact outcome fault E exists to
    prevent, arrived at from the opposite direction. A failure here is logged at ERROR with
    a token the alarm can grep, and the run continues: the rows were already going to be
    dropped, so the worst case is that they are dropped the way they always were.
    """
    if not rows:
        return 0

    key = quarantine_key(dataset, year, numero_sorteo, run_id)
    try:
        buffer = io.BytesIO()
        _typed_frame(rows).to_parquet(buffer, index=False)
        buffer.seek(0)
        (s3_client or _s3()).put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())
    except Exception as exc:
        logger.error(
            "%s dataset=%s sorteo=%s rows=%d error=%s: %s",
            QUARANTINE_WRITE_FAILED,
            dataset,
            numero_sorteo,
            len(rows),
            type(exc).__name__,
            exc,
        )
        return 0

    logger.info(
        "Quarantined rows written",
        extra={
            "dataset": dataset,
            "numero_sorteo": numero_sorteo,
            "rows": len(rows),
            "key": key,
        },
    )
    return len(rows)


#: Grepped by a CloudWatch metric filter, same pattern as PR-042.2's retention alarm and for
#: the same reason: this failure is swallowed by design, so nothing else in the system will
#: ever mention it. A literal, stable token — a metric filter matches text, and a reworded
#: log line silently turns the alarm off.
QUARANTINE_WRITE_FAILED = "QUARANTINE_WRITE_FAILED"

#: Grepped by the other metric filter: the signal PR-044.1 measured. The archive baseline is
#: **one** occurrence in 118 draws, so "> 0 in a run" is an alarm worth reading rather than
#: one that fires every Thursday.
QUARANTINED_UNRECOGNISED = "QUARANTINED_UNRECOGNISED"
