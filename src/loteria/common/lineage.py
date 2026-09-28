"""The lineage contract for Silver (PR-045.1, fault F).

**The defect this closes.** Silver Parquet carried only business columns. PR-018 already
threads a ``correlation_id`` through the *logs* of every stage, but it never reached the
*data* — so "which run produced these rows?" was answered by correlating S3 object
timestamps against CloudWatch by hand, and after a re-scrape there was no way at all to tell
old rows from new ones.

Four columns, defined here rather than inline in the transformer so that the writer
(``loteria.transformer``), the data-quality suites (``loteria.dq.suites``) and the loader
(``loteria.dq.runner``) all agree by construction instead of by three people remembering.

``run_id``
    The PR-018 correlation id — the Step Functions execution name — bridged into the Glue
    job's environment by ``scripts/glue_zip_main.py``. **Deliberately NULL when absent.**
    See ``run_id_from_env`` for why that is the useful behaviour rather than a gap.

``ingested_at``
    When the transformer wrote the file. UTC, and **timezone-naive on purpose** — see
    ``INGESTED_AT_IS_NAIVE_UTC`` below.

``source_key``
    The ``raw/`` S3 key the row was derived from. The one column that makes a row traceable
    to a specific scrape rather than to a run: a single run writes many sorteos.

``parser_version``
    Bumped **by hand** when the parse changes shape. It is what makes a reprocessing
    decision answerable later — "were these rows produced by the parser that had the
    truncating date regex?" is a question about the parser, not about the run, and no
    timestamp answers it.

**What is deliberately NOT here: a backfill.** The 222 pre-lineage files keep NULLs. A
backfilled ``ingested_at`` is a lie, and a fabricated ``run_id`` is worse than a null one,
because it claims a provenance that was never recorded. NULL correctly means "written
before lineage existed", and it is greppable. The sentinel backfill stays a separate PR to
be decided on its own merits.
"""

from __future__ import annotations

import datetime as dt
import os

#: Bump by hand when the parse changes shape — a new column, a changed regex, a different
#: split. It is not a release number and it does not track the repo version: it answers
#: "which parsing behaviour produced this row?", so it only moves when that behaviour does.
#:
#: 1 — the shape as of PR-045.1 (post PR-035.1's anchored draw-date regex).
PARSER_VERSION = 1

RUN_ID = "run_id"
INGESTED_AT = "ingested_at"
SOURCE_KEY = "source_key"
PARSER_VERSION_COLUMN = "parser_version"

#: Order is the order they are appended to each Silver frame, so the Parquet column order is
#: stable across runs and a schema diff stays readable.
LINEAGE_COLUMNS = (RUN_ID, INGESTED_AT, SOURCE_KEY, PARSER_VERSION_COLUMN)

#: What the Glue catalog declares for each column, and therefore what the Parquet must
#: physically hold (PR-045.2). The other half of this contract is
#: ``terraform/modules/catalog/main.tf``'s ``local.lineage_columns``; a test reads the
#: ``.tf`` and compares, because nothing else would notice the two drifting apart.
#:
#: **``parser_version`` is ``bigint``, not ``int``.** pandas writes a Python int as int64, so
#: the Parquet holds 64 bits. Athena widens INT to BIGINT and supports no conversion in the
#: other direction, so an ``int`` declaration over this data is a read error waiting for
#: someone to run the query.
#:
#: The two string columns are why ``transformer`` and ``quarantine`` cast before writing: an
#: all-``None`` column — which ``run_id`` legitimately is whenever a write did not come from
#: a pipeline run — is written to Parquet as the **Null** type, not as a string, and a
#: declared ``string`` over it does not match.
LINEAGE_GLUE_TYPES = {
    RUN_ID: "string",
    INGESTED_AT: "timestamp",
    SOURCE_KEY: "string",
    PARSER_VERSION_COLUMN: "bigint",
}

#: ``ingested_at`` is stored as a timezone-NAIVE UTC timestamp, and that is a decision worth
#: writing down because "naive" usually means "careless".
#:
#: Athena's ``timestamp`` type has no zone, and the two business date columns already in this
#: table (``fecha_sorteo``, ``fecha_caducidad``) are naive. Writing this one as tz-aware
#: would make it the single column in Silver with a different temporal type, which the Glue
#: crawler and Athena each handle in their own way — and tz-aware pandas columns land in
#: Parquet as ``timestamp[ns, tz=UTC]``, a precision Athena has historically been fussy
#: about. So: naive, UTC by construction, never local time, and the name of this constant is
#: the documentation that survives a copy-paste of the column into somewhere else.
INGESTED_AT_IS_NAIVE_UTC = True


def utc_now() -> dt.datetime:
    """The value written to ``ingested_at``: UTC, naive, microsecond precision.

    Naive by way of an explicit conversion from an aware value, not by calling
    ``datetime.utcnow()``. The two produce the same number today, but ``utcnow()`` returns a
    naive value *labelled* nothing, so a reader cannot tell whether the author meant UTC or
    forgot about zones — and it is deprecated in 3.12 for exactly that reason.
    """
    # noqa: UP017 is load-bearing, not noise. ruff targets py312 (pyproject) and wants
    # `dt.UTC` here — an alias that did not exist before Python 3.11. This module ships
    # inside the Glue zip, and the transform job is a **Python Shell job pinned to 3.9**
    # (`PythonVersion: "3.9"`; Python Shell offers 3.6 or 3.9 and nothing else). Taking
    # ruff's advice would import fine on the 3.12 Lambda, pass CI, and raise
    # AttributeError in the weekly Glue run. Anything under `loteria/` that Glue imports
    # has to stay 3.9-compatible regardless of what the linter targets.
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)  # noqa: UP017


def run_id_from_env(env: dict | None = None) -> str | None:
    """The Step Functions execution name, or ``None`` when this write is not from a run.

    **The ``None`` is the point, not a fallback.** A tempting alternative is to substitute
    something like ``"manual"`` or the hostname, so the column is never empty. That would
    make the column always-populated and therefore useless: the data-quality gate's whole
    contribution here is ``run_id is not null`` on lineage-era rows, which is the only check
    in the project that can notice **something wrote Silver outside the pipeline**. A
    substituted value silently answers the question the gate is asking.

    So a hand-run transform that writes Silver without a correlation id will turn the gate
    red. That is the intended behaviour: it did write Silver outside the pipeline.
    """
    source = os.environ if env is None else env
    value = (source.get("CORRELATION_ID") or "").strip()
    return value or None
