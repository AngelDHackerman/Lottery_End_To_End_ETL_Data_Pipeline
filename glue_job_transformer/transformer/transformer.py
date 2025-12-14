"""
Transformer (Glue Job)

Goal:
- Read raw .txt files from the partitioned bucket (raw/year=YYYY/sorteo=NNNN/...)
- Parse into two DataFrames: sorteos + premios
- Enforce a *stable Silver schema* (types + partitions)
- Write Parquet to:
  - Partitioned bucket (Silver): silver/{dataset}/year=YYYY/sorteo=NNNN/{dataset}.parquet
  - Simple bucket (optional, flat files): <SIMPLE_PREFIX>/sorteos_<NNNN>.parquet, premios_<NNNN>.parquet

Important:
- NEVER mix schemas in the same S3 prefix.
- Partitions (year, sorteo) must be added BEFORE writing Parquet.
"""

import sys
import os
import re
import pandas as pd
from awsglue.utils import getResolvedOptions

from parser.parser import (
    split_header_body,
    process_header,
    process_body,
    split_vendido_por_column,
)

from extractor.s3_utils import (
    list_files_in_s3,
    list_processed_sorteos_in_partitioned_bucket,
    download_file_from_s3,
    upload_file_to_s3,
)

from extractor.aws_secrets import get_secrets


# -----------------------
# Config
# -----------------------
buckets = get_secrets()
partitioned_bucket = buckets["partitioned"]
simple_bucket = buckets["simple"]

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
    simple_prefix: str,
    silver_prefix: str = SILVER_PREFIX_DEFAULT,
) -> None:
    """
    Transforms raw lottery .txt files stored in S3 and uploads clean Silver Parquet files back to S3.
    """

    # ✅ Idempotency check must be against SILVER (not legacy/processed)
    processed_sorteos = list_processed_sorteos_in_partitioned_bucket(
        bucket_name,
        prefix=f"{silver_prefix}sorteos/",
    )

    raw_files = list_files_in_s3(bucket_name, raw_prefix)

    print(f"Found {len(raw_files)} raw files in S3 under prefix: {raw_prefix}")
    print(f"Found {len(processed_sorteos)} sorteos already processed in Silver")

    for raw_file in raw_files:
        # Expect: raw/year=YYYY/sorteo=NNNN/<file>.txt
        match = re.search(r"sorteo=(\d+)/", raw_file)
        if not match:
            print(f"Skipping file with unexpected structure: {raw_file}")
            continue

        numero_sorteo = int(match.group(1))
        if numero_sorteo in processed_sorteos:
            print(f"Skipping already processed sorteo {numero_sorteo}")
            continue

        local_path = f"/tmp/{os.path.basename(raw_file)}"
        download_file_from_s3(bucket_name, raw_file, local_path)

        with open(local_path, "r", encoding="utf-8") as f:
            file_content = f.read()

        header_lines, body_lines = split_header_body(file_content.splitlines())

        # Parse into python objects
        sorteos = [process_header(header_lines)]
        premios = process_body(body_lines)

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
            ["numero_sorteo", "numero_premiado", "letras", "monto", "vendedor", "ciudad", "departamento"]
        ]

        # -----------------------
        # Enforce PREMIOS schema (Silver)
        # -----------------------
        premios_df.replace({"N/A": None, "n/a": None, "": None}, inplace=True)

        premios_df["numero_sorteo"] = _to_int64(premios_df["numero_sorteo"], default=0)  # int64
        premios_df["numero_premiado"] = _to_int64(premios_df["numero_premiado"])         # nullable Int64
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
            raise ValueError(f"Invalid fecha_sorteo for sorteo={numero_sorteo}. Cannot derive year partition.")

        year = int(sorteos_df["fecha_sorteo"].dt.year.iloc[0])

        # -----------------------
        # Write Parquet locally
        # -----------------------
        sorteos_local_path = f"/tmp/sorteos_{numero_sorteo}.parquet"
        premios_local_path = f"/tmp/premios_{numero_sorteo}.parquet"

        sorteos_df.to_parquet(sorteos_local_path, index=False)
        premios_df.to_parquet(premios_local_path, index=False)

        # -----------------------
        # Upload to simple bucket (flat files) - optional but useful for notebooks
        # -----------------------
        sorteos_key_simple = f"{simple_prefix}sorteos_{numero_sorteo}.parquet"
        premios_key_simple = f"{simple_prefix}premios_{numero_sorteo}.parquet"

        upload_file_to_s3(sorteos_local_path, simple_bucket, sorteos_key_simple)
        upload_file_to_s3(premios_local_path, simple_bucket, premios_key_simple)

        # -----------------------
        # Upload to partitioned bucket (Silver - canonical)
        # -----------------------
        partitioned_sorteos_key = (
            f"{silver_prefix}sorteos/year={year}/sorteo={numero_sorteo}/sorteos.parquet"
        )
        partitioned_premios_key = (
            f"{silver_prefix}premios/year={year}/sorteo={numero_sorteo}/premios.parquet"
        )

        upload_file_to_s3(sorteos_local_path, partitioned_bucket, partitioned_sorteos_key)
        upload_file_to_s3(premios_local_path, partitioned_bucket, partitioned_premios_key)

        print(f"✅ Sorteo {numero_sorteo} processed successfully into Silver (year={year})")


def main() -> None:
    """
    Entry point when running as a Glue Job.
    Parameters:
      - SIMPLE_BUCKET
      - PARTITIONED_BUCKET
      - RAW_PREFIX
      - PROCESSED_PREFIX (we will treat this as the *simple bucket prefix*)
    """
    args = getResolvedOptions(
        sys.argv,
        [
            "SIMPLE_BUCKET",
            "PARTITIONED_BUCKET",
            "RAW_PREFIX",
            "PROCESSED_PREFIX",
        ],
    )

    # Allow runtime overrides
    global partitioned_bucket, simple_bucket

    if args.get("PARTITIONED_BUCKET"):
        partitioned_bucket = args["PARTITIONED_BUCKET"]

    if args.get("SIMPLE_BUCKET"):
        simple_bucket = args["SIMPLE_BUCKET"]

    raw_prefix = args["RAW_PREFIX"]
    simple_prefix = args["PROCESSED_PREFIX"]  # treat as simple prefix

    print(f"Starting Glue Job. Partitioned bucket: {partitioned_bucket}")
    print(f"Raw prefix: {raw_prefix}")
    print(f"Simple output prefix: {simple_prefix}")
    print(f"Silver prefix: {SILVER_PREFIX_DEFAULT}")

    transform(
        bucket_name=partitioned_bucket,
        raw_prefix=raw_prefix,
        simple_prefix=simple_prefix,
        silver_prefix=SILVER_PREFIX_DEFAULT,
    )

    print("Glue Job finished!")


if __name__ == "__main__":
    main()
