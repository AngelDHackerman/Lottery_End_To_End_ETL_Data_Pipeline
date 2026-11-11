"""Write terraform/uy/silver_tables.json: UY silver as the Glue catalog needs it (UY-044.1).

    python scripts/uy_catalog_schema.py            # rewrite the file
    python scripts/uy_catalog_schema.py --check    # exit 1 if the file is not what this prints

The schemas have one source, `sorteos.core.silver.TABLES`: the same pyarrow schemas the writer
enforces on every file. Terraform reads the JSON (catalog.tf), so a table Athena declares can
never drift from the Parquet behind it: a test runs `--check`, and a column added to silver
without regenerating this file turns CI red.

No crawler (owner, UY-044 3a): Santa Lucía's proved it cannot follow a schema change (PR-045).
The partitions are not registered either. They are *projected*: Athena computes them from the
table's properties, so a new year is readable the night the silver Lambda writes it, with no
`MSCK REPAIR`, no `ADD PARTITION` and nobody to forget either.

Lives in scripts/, not in src/sorteos: everything under src/sorteos ships in the fetch zip
and sets the silver image's tag, and a catalog change should not redeploy two Lambdas.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pyarrow as pa

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sorteos.core import silver  # noqa: E402

OUT = ROOT / "terraform" / "uy" / "silver_tables.json"
GAMES_DIR = ROOT / "src" / "sorteos" / "uy" / "games"
COUNTRY = "uy"
FIRST_YEAR = 2006  # site.yaml, history_starts
# An integer projection needs a fixed upper bound (only date projections know NOW). Athena
# lists one S3 prefix per projected partition when a query does not filter on year, so the
# bound is near rather than 9999. tests/unit/sorteos/test_uy_catalog.py fails two years
# before it is reached: a year past the bound would be written to S3 and invisible to Athena.
LAST_YEAR = 2040


class CatalogError(ValueError):
    pass


def glue_type(kind: pa.DataType) -> str:
    """The Athena/Hive type of a pyarrow type. Unknown types raise: never guess a type."""
    if pa.types.is_string(kind):
        return "string"
    if pa.types.is_date32(kind):
        return "date"
    if pa.types.is_int32(kind):
        return "int"
    if pa.types.is_boolean(kind):
        return "boolean"
    if pa.types.is_timestamp(kind) and kind.tz is None:
        return "timestamp"
    if pa.types.is_decimal(kind):
        return f"decimal({kind.precision},{kind.scale})"
    if pa.types.is_list(kind):
        return f"array<{glue_type(kind.value_type)}>"
    raise CatalogError(f"no Glue type for {kind}")


def games() -> list[str]:
    return sorted(p.stem for p in GAMES_DIR.glob("*.yaml"))


def _projection(column: str) -> dict[str, str]:
    if column == "country":
        return {"type": "enum", "values": COUNTRY}
    if column == "game":
        return {"type": "enum", "values": ",".join(games())}
    if column == "year":
        return {"type": "integer", "range": f"{FIRST_YEAR},{LAST_YEAR}"}
    raise CatalogError(f"no projection for partition column {column}")


def table(spec: silver.Table) -> dict:
    """Columns as in the file, then the path columns in path order (year= last)."""
    partition = [(name, "string") for name in spec.partition]
    if spec.year_of is not None:
        partition.append(("year", "int"))
    return {
        "columns": [{"name": f.name, "type": glue_type(f.type)} for f in spec.file_schema],
        "partition_keys": [{"name": n, "type": t} for n, t in partition],
        "projection": {n: _projection(n) for n, _ in partition},
    }


def catalog() -> dict:
    return {
        "_generated_by": "scripts/uy_catalog_schema.py — do not edit; run `make uy-catalog-sync`",
        "tables": {name: table(spec) for name, spec in sorted(silver.TABLES.items())},
    }


def render() -> str:
    return json.dumps(catalog(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare, do not write")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        if not OUT.exists() or OUT.read_text("utf-8") != text:
            print(f"{OUT.relative_to(ROOT)} is stale: run `make uy-catalog-sync` and commit it")
            return 1
        print(f"{OUT.relative_to(ROOT)} matches sorteos.core.silver.TABLES")
        return 0
    OUT.write_text(text, "utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(catalog()['tables'])} tables")
    return 0


if __name__ == "__main__":
    sys.exit(main())
