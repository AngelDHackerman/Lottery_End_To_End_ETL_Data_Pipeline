"""
Transformer (Glue Job)

Goal:
- Read raw .txt files from the partitioned bucket (raw/year=YYYY/sorteo=NNNN/...)
- Parse into two DataFrames: sorteos + premios
- Enforce a *stable Silver schema* (types + partitions)
- Write Parquet to ONE place — the partitioned bucket's Silver layer:
  silver/{dataset}/year=YYYY/sorteo=NNNN/{dataset}.parquet

  Until PR-041.2 every draw was also written flat to a second bucket. That copy had no
  reader (docs/inventory/2026-09-20-simple-bucket-readers.md); Silver is the source of
  truth and now the only write target.

Important:
- NEVER mix schemas in the same S3 prefix.
- Partitions (year, sorteo) must be added BEFORE writing Parquet.
"""

import logging
import os
import re
import sys

import pandas as pd
from awsglue.utils import getResolvedOptions

from loteria.common import quarantine
from loteria.common.aws_secrets import get_secrets
from loteria.common.lineage import (
    INGESTED_AT,
    PARSER_VERSION,
    PARSER_VERSION_COLUMN,
    RUN_ID,
    SOURCE_KEY,
    run_id_from_env,
    utc_now,
)
from loteria.common.logging_setup import configure_logging
from loteria.common.s3_utils import (
    download_file_from_s3,
    list_files_in_s3,
    list_processed_sorteos_in_partitioned_bucket,
    upload_file_to_s3,
)
from loteria.parser.parser import (
    REJECT_LINE_MAX,
    REJECT_UNRECOGNISED,
    process_body,
    process_header,
    split_header_body,
    split_vendido_por_column,
)

logger = logging.getLogger(__name__)

# -----------------------
# Config
# -----------------------
buckets = get_secrets()
# The FALLBACK bucket for main() only. transform() never reads this: it reads and writes the
# `bucket_name` it is given (PR-048 — it used to write here, so any caller passing a
# different bucket read from one and wrote Silver into the other, with no error).
partitioned_bucket = buckets["partitioned"]

SILVER_PREFIX_DEFAULT = "silver/"  # The new Source of Truth for clean Parquet
SILVER_SORTEOS_PREFIX = f"{SILVER_PREFIX_DEFAULT}sorteos/"
SILVER_PREMIOS_PREFIX = f"{SILVER_PREFIX_DEFAULT}premios/"


def _to_int64(series: pd.Series, default=None) -> pd.Series:
    """
    Convert a Series to nullable Int64 (supports NA).
    If default is provided, NA will be replaced with that value and cast to int64.
    """
    s = pd.to_numeric(series, errors="coerce").astype("Int64")
    if default is not None:
        s = s.fillna(default).astype("int64")
    return s


def _to_float64(series: pd.Series, default=0.0) -> pd.Series:
    """
    Convert a Series to float64, replacing invalid values with a default.
    """
    return pd.to_numeric(series, errors="coerce").fillna(default).astype("float64")


def _to_string(series: pd.Series) -> pd.Series:
    """
    Use pandas StringDtype to keep nulls as <NA> instead of 'nan' strings.
    """
    return series.astype("string")


def transform(
    bucket_name: str,
    raw_prefix: str,
    silver_prefix: str = SILVER_PREFIX_DEFAULT,
) -> None:
    """
    Transforms raw lottery .txt files stored in S3 and uploads clean Silver Parquet
    files back to S3.

    One bucket in both directions: raw is read from ``bucket_name`` and Silver and
    quarantine are written to ``bucket_name``. Nothing here reads the module global.
    """

    # ✅ Idempotency check must be against SILVER (not legacy/processed)
    processed_sorteos = list_processed_sorteos_in_partitioned_bucket(
        bucket_name,
        prefix=f"{silver_prefix}sorteos/",
    )

    raw_files = list_files_in_s3(bucket_name, raw_prefix)

    logger.info(
        "Scanned raw + Silver layers",
        extra={
            "raw_files": len(raw_files),
            "processed_sorteos": len(processed_sorteos),
            "raw_prefix": raw_prefix,
        },
    )

    # PR-045.1: resolved ONCE per transform, not per sorteo — every row this job writes
    # belongs to the same run by definition, and re-reading the environment inside the loop
    # would only create a way for them to disagree. None here means the gate will go red,
    # which is the intended signal; see `run_id_from_env`.
    run_id = run_id_from_env()
    logger.info(
        "Lineage stamp for this transform",
        extra={"run_id": run_id, "parser_version": PARSER_VERSION},
    )

    quarantined_total = 0
    unrecognised_total = 0

    for raw_file in raw_files:
        # Expect: raw/year=YYYY/sorteo=NNNN/<file>.txt
        match = re.search(r"sorteo=(\d+)/", raw_file)
        if not match:
            # PR-044.2: was a warning and a `continue` — the same silent-loss shape as the
            # per-line skips, one level up. The file is still skipped; it is now also kept.
            logger.warning("Skipping file with unexpected structure", extra={"raw_file": raw_file})
            quarantined_total += quarantine.write(
                bucket_name,
                quarantine.build_rows(
                    [
                        {
                            "reason": quarantine.REJECT_UNEXPECTED_KEY,
                            "line": raw_file[:REJECT_LINE_MAX],
                            "position": 0,
                        }
                    ],
                    source_key=raw_file,
                    run_id=run_id,
                ),
                dataset="sorteos",
                year="unknown",
                numero_sorteo="unknown",
                run_id=run_id,
            )
            continue

        numero_sorteo = int(match.group(1))
        if numero_sorteo in processed_sorteos:
            logger.info("Skipping already processed sorteo", extra={"sorteo_number": numero_sorteo})
            continue

        # PR-034, on this line's B108 suppression and the two on the Parquet paths below.
        # Bandit flags every hardcoded /tmp path, because on a shared multi-user host it is
        # world-writable and predictable. Neither applies in Glue or Lambda: each job run
        # gets its own container with a private /tmp that is destroyed afterwards, and it is
        # the ONLY writable filesystem those runtimes offer. `tempfile.mkstemp` would land
        # in the same directory and buy nothing.
        #
        # This comment spells the marker "B108" instead of writing it out, because bandit
        # scans comment TEXT for its suppression token — an explanation that quotes the token
        # becomes a suppression itself and silently disables the check.
        local_path = f"/tmp/{os.path.basename(raw_file)}"  # nosec B108
        download_file_from_s3(bucket_name, raw_file, local_path)

        with open(local_path, encoding="utf-8") as f:
            file_content = f.read()

        # PR-044.2 — PR-035.1's defect C. `process_header` raises ValueError on a header
        # missing REINTEGROS, and until now NOTHING caught it: the exception aborted the run
        # for every OTHER raw file in the batch, before anything was written. One draw with
        # an odd header was a full weekly outage rather than one skipped record.
        #
        # ⚠️ ValueError ONLY, deliberately narrow. A ValueError here means "this input is not
        # what the parser expects", which is precisely what quarantine is for. A broad
        # `except Exception` would also swallow an S3 failure, an out-of-memory, a bug in
        # this module — infrastructure problems that SHOULD fail the run loudly, and that
        # would otherwise be silently reclassified as bad data. Quarantining a genuine bug
        # is how a pipeline learns to lie about its own health.
        try:
            header_lines, body_lines = split_header_body(file_content.splitlines())
            sorteos = [process_header(header_lines)]
            # PR-044.1: `rejects` is what used to disappear into a DEBUG log Glue never
            # emitted — counted and logged there, persisted here.
            premios, premios_rejects = process_body(body_lines)
        except ValueError as exc:
            logger.warning(
                "Sorteo quarantined: the file did not parse",
                extra={
                    "sorteo_number": numero_sorteo,
                    "raw_file": raw_file,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            rows = quarantine.build_rows(
                [
                    {
                        "reason": quarantine.REJECT_MALFORMED_HEADER,
                        "line": str(exc)[:REJECT_LINE_MAX],
                        "position": 0,
                    }
                ],
                source_key=raw_file,
                run_id=run_id,
            )
            # `year` comes from fecha_sorteo, which is exactly what failed to parse. The raw
            # key carries one, so use it and fall back to "unknown" rather than inventing.
            year_match = re.search(r"year=(\d{4})/", raw_file)
            quarantined_total += quarantine.write(
                bucket_name,
                rows,
                dataset="sorteos",
                year=year_match.group(1) if year_match else "unknown",
                numero_sorteo=numero_sorteo,
                run_id=run_id,
            )
            continue

        # Attach numero_sorteo to each premio row
        for premio in premios:
            premio["numero_sorteo"] = sorteos[0]["numero_sorteo"]

        # -----------------------
        # DataFrames
        # -----------------------
        sorteos_df = pd.DataFrame(sorteos)
        premios_df = pd.DataFrame(premios)

        # Split vendido_por into vendor/city/department
        premios_df = split_vendido_por_column(premios_df)

        # Normalize "DE ESTA CAPITAL" -> department = GUATEMALA
        # Use fillna("") to avoid errors when ciudad is null
        mask_capital = premios_df["ciudad"].fillna("").str.upper().eq("DE ESTA CAPITAL")
        premios_df.loc[mask_capital, "departamento"] = "GUATEMALA"

        # Keep only the columns you want in Silver
        premios_df = premios_df[
            [
                "numero_sorteo",
                "numero_premiado",
                "letras",
                "monto",
                "vendedor",
                "ciudad",
                "departamento",
            ]
        ]

        # -----------------------
        # Enforce PREMIOS schema (Silver)
        # -----------------------
        premios_df.replace({"N/A": None, "n/a": None, "": None}, inplace=True)

        premios_df["numero_sorteo"] = _to_int64(premios_df["numero_sorteo"], default=0)  # int64
        premios_df["numero_premiado"] = _to_int64(premios_df["numero_premiado"])  # nullable Int64
        premios_df["monto"] = _to_float64(premios_df["monto"], default=0.0)

        premios_df["letras"] = _to_string(premios_df["letras"])
        premios_df["vendedor"] = _to_string(premios_df["vendedor"])
        premios_df["ciudad"] = _to_string(premios_df["ciudad"])
        premios_df["departamento"] = _to_string(premios_df["departamento"])

        # -----------------------
        # Enforce SORTEOS schema (Silver)
        # -----------------------

        # Split reintegros into 3 columns (defensive)
        if "reintegros" in sorteos_df.columns:
            reintegro_split = sorteos_df["reintegros"].astype("string").str.split(",", expand=True)
            # If the split produces fewer than 3 columns, pad them
            while reintegro_split.shape[1] < 3:
                reintegro_split[reintegro_split.shape[1]] = None

            sorteos_df["reintegro_primer_premio"] = reintegro_split[0]
            sorteos_df["reintegro_segundo_premio"] = reintegro_split[1]
            sorteos_df["reintegro_tercer_premio"] = reintegro_split[2]

            sorteos_df.drop(columns=["reintegros"], inplace=True, errors="ignore")
        else:
            sorteos_df["reintegro_primer_premio"] = None
            sorteos_df["reintegro_segundo_premio"] = None
            sorteos_df["reintegro_tercer_premio"] = None

        # Convert reintegros to int
        for col in [
            "reintegro_primer_premio",
            "reintegro_segundo_premio",
            "reintegro_tercer_premio",
        ]:
            sorteos_df[col] = _to_int64(sorteos_df[col])

        # Convert core numeric columns
        sorteos_df["numero_sorteo"] = _to_int64(sorteos_df["numero_sorteo"], default=0)  # int64
        sorteos_df["primer_premio"] = _to_int64(sorteos_df["primer_premio"])
        sorteos_df["segundo_premio"] = _to_int64(sorteos_df["segundo_premio"])
        sorteos_df["tercer_premio"] = _to_int64(sorteos_df["tercer_premio"])

        # Convert dates (this is what enables ORDER BY, filters, and time features)
        sorteos_df["fecha_sorteo"] = pd.to_datetime(
            sorteos_df["fecha_sorteo"],
            format="%d/%m/%Y",
            errors="coerce",
        )
        sorteos_df["fecha_caducidad"] = pd.to_datetime(
            sorteos_df["fecha_caducidad"],
            format="%d/%m/%Y",
            errors="coerce",
        )

        # Derive partition year safely
        if sorteos_df["fecha_sorteo"].isna().all():
            raise ValueError(
                f"Invalid fecha_sorteo for sorteo={numero_sorteo}. Cannot derive year partition."
            )

        year = int(sorteos_df["fecha_sorteo"].dt.year.iloc[0])

        # -----------------------
        # Lineage (PR-045.1, fault F)
        # -----------------------
        # Applied to BOTH frames and applied LAST, after every business column exists and
        # after `year` has been derived. Last on purpose: these four columns describe the
        # write, so anything that can still raise above this point should raise before a row
        # is stamped as having been produced by this run.
        #
        # `ingested_at` is computed once per sorteo rather than once per frame, so a sorteo's
        # two files carry the SAME instant. Two timestamps microseconds apart would look like
        # evidence of something when it is only evidence of two statements.
        #
        # ⚠️ PR-045.2: the two string columns are cast, and the cast is load-bearing.
        # `frame[RUN_ID] = None` leaves an all-None object column, and pyarrow types an
        # all-None column as Parquet **Null** (physically `optional int32 (Null)`), not as a
        # string. That was invisible while nothing read Silver by its declared schema; now
        # that the catalog declares `run_id string`, such a file is a type mismatch — and
        # Athena's one unreadable file would be a whole partition the seven gold CTAS cannot
        # read. The case is not hypothetical: PR-045.1 accepts, by design, that a hand-run
        # transform without CORRELATION_ID writes a NULL `run_id`.
        ingested_at = utc_now()
        for frame in (sorteos_df, premios_df):
            frame[RUN_ID] = run_id
            frame[INGESTED_AT] = ingested_at
            frame[SOURCE_KEY] = raw_file
            frame[PARSER_VERSION_COLUMN] = PARSER_VERSION
            # Assign-then-cast rather than a typed constructor: `frame[col] = <scalar>`
            # behaves identically on the Glue 3.9 pandas and on the 3.x one the tests run,
            # and `_to_string` is the same helper every other Silver string column goes
            # through.
            frame[RUN_ID] = _to_string(frame[RUN_ID])
            frame[SOURCE_KEY] = _to_string(frame[SOURCE_KEY])

        # -----------------------
        # Write Parquet locally
        # -----------------------
        sorteos_local_path = f"/tmp/sorteos_{numero_sorteo}.parquet"  # nosec B108
        premios_local_path = f"/tmp/premios_{numero_sorteo}.parquet"  # nosec B108

        sorteos_df.to_parquet(sorteos_local_path, index=False)
        premios_df.to_parquet(premios_local_path, index=False)

        # -----------------------
        # Upload to partitioned bucket (Silver — the only write target, PR-041.2)
        # -----------------------
        partitioned_sorteos_key = (
            f"{silver_prefix}sorteos/year={year}/sorteo={numero_sorteo}/sorteos.parquet"
        )
        partitioned_premios_key = (
            f"{silver_prefix}premios/year={year}/sorteo={numero_sorteo}/premios.parquet"
        )

        # PR-048: the bucket the raw file came from, not the module global.
        upload_file_to_s3(sorteos_local_path, bucket_name, partitioned_sorteos_key)
        upload_file_to_s3(premios_local_path, bucket_name, partitioned_premios_key)

        # PR-044.2: persist what PR-044.1 only counted. `build_rows` drops `section_header`
        # — 6.5% of every body is millar headings, and storing them would write ~9,500 rows
        # of structure per draw and make `SELECT reason, count(*)` useless.
        unrecognised = sum(1 for r in premios_rejects if r["reason"] == REJECT_UNRECOGNISED)
        quarantined = quarantine.write(
            bucket_name,
            quarantine.build_rows(
                premios_rejects,
                source_key=raw_file,
                run_id=run_id,
            ),
            dataset="premios",
            year=year,
            numero_sorteo=numero_sorteo,
            run_id=run_id,
        )
        quarantined_total += quarantined
        unrecognised_total += unrecognised
        if unrecognised:
            # The signal the alarm greps for. Measured baseline across the whole archive:
            # ONE occurrence in 145,680 lines, so this is worth an email when it happens.
            logger.warning(
                "%s sorteo=%s count=%d",
                quarantine.QUARANTINED_UNRECOGNISED,
                numero_sorteo,
                unrecognised,
            )

        logger.info(
            "Sorteo processed successfully into Silver",
            extra={
                "sorteo_number": numero_sorteo,
                "year": year,
                # PR-044.1: per-sorteo reject counts, so a run's log answers "how much did
                # we drop, and was any of it surprising?" without anyone opening the parser.
                # `unrecognised` is the one that matters — baseline across the whole
                # archive is 1 line in 145,680.
                "rejected_total": len(premios_rejects),
                "rejected_unrecognised": unrecognised,
                "quarantined": quarantined,
            },
        )


def main() -> None:
    """
    Entry point when running as a Glue Job.
    Parameters:
      - PARTITIONED_BUCKET
      - RAW_PREFIX

    PR-041.2 removed three more: ``SIMPLE_BUCKET``, ``PROCESSED_PREFIX`` (which named a
    prefix in the *simple* bucket, not the legacy ``processed/`` its name suggests) and
    ``ENABLE_SIMPLE_BUCKET_WRITES``. ``getResolvedOptions`` ignores arguments it was not
    asked for, so a job still carrying them in its default_arguments starts fine — which
    is what makes the code deploy and the ``terraform apply`` independent of each other.
    """
    # Configure JSON logging here (not in transformer/__main__.py) because the REAL Glue
    # entry point is the zip-root __main__.py from scripts/glue_zip_main.py, which imports
    # this main() directly — so this is the one place both entry paths pass through. The
    # correlation_id is read from the CORRELATION_ID env var, which glue_zip_main.py has
    # already bridged from the --CORRELATION_ID job argument.
    configure_logging("transformer")

    args = getResolvedOptions(
        sys.argv,
        [
            "PARTITIONED_BUCKET",
            "RAW_PREFIX",
        ],
    )

    # The job argument wins; an empty one falls back to the secret rather than pointing the
    # job at a bucket named "". Resolved into a local (PR-048): main() used to overwrite the
    # module global, which was the only thing keeping transform()'s write in the same
    # bucket as its read.
    bucket = args.get("PARTITIONED_BUCKET") or partitioned_bucket

    raw_prefix = args["RAW_PREFIX"]

    logger.info(
        "Starting Glue Job",
        extra={
            "partitioned_bucket": bucket,
            "raw_prefix": raw_prefix,
            "silver_prefix": SILVER_PREFIX_DEFAULT,
        },
    )

    transform(
        bucket_name=bucket,
        raw_prefix=raw_prefix,
        silver_prefix=SILVER_PREFIX_DEFAULT,
    )

    logger.info("Glue Job finished")


if __name__ == "__main__":
    main()
