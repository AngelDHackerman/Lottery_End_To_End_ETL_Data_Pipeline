"""Build UY gold locally with DuckDB, from the same SQL Athena will run (UY-032, UY-044.2).

    python scripts/uy_gold_local.py --silver data/uy/silver --out data/uy/gold

Every file of sql/uy/gold/ is one SELECT over the silver tables (`silver_draws`, ...), written
for Athena and kept to what both engines read the same way (sql/uy/gold/README.md lists what
had to be avoided). Here each silver table is a DuckDB view over its Parquet folder, each
SELECT is run as it is, and its result is written to <out>/<table>/part-0.parquet. Nothing
touches AWS.

It then prints, per table, what was expected and what was observed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql" / "uy" / "gold"
FILE_NAME = "part-0.parquet"
# The silver tables and whether their path has year= (terraform/uy/silver_tables.json says the
# same; here it only decides the type DuckDB gives the partition column).
SILVER = {
    "draws": True,
    "draw_numbers": True,
    "prizes": True,
    "quarantine": True,
    "game_rules": False,
    "calendar_events": False,
    "draw_gaps": False,
}
_FILE_RE = re.compile(r"^\d{2}_(gold_[a-z0-9_]+)\.sql$")


class GoldError(ValueError):
    pass


def queries(sql_dir: Path = SQL_DIR) -> dict[str, str]:
    """{table: SELECT}, in file order. A file that is not NN_gold_<name>.sql is an error."""
    found: dict[str, str] = {}
    for path in sorted(sql_dir.glob("*.sql")):
        match = _FILE_RE.match(path.name)
        if not match:
            raise GoldError(f"{path.name}: expected NN_gold_<name>.sql")
        text = path.read_text("utf-8").strip().rstrip(";").strip()
        if not text:
            raise GoldError(f"{path.name} is empty")
        found[match.group(1)] = text
    if not found:
        raise GoldError(f"no SQL files in {sql_dir}")
    return found


def connect(silver: Path) -> duckdb.DuckDBPyConnection:
    """An in-memory database with one view per silver table that has files.

    `year` is read as INTEGER, the type the Glue catalog declares: DuckDB would infer BIGINT
    from the path. A table with no files (quarantine, almost always) gets no view: no gold
    query reads it, and one that did would fail loudly here instead of counting nothing.
    """
    silver = Path(silver)
    if not silver.is_dir():
        raise GoldError(f"no silver at {silver}")
    con = duckdb.connect()
    for name, by_year in SILVER.items():
        folder = silver / name
        if not any(folder.rglob("*.parquet")):
            continue
        types = ", hive_types = {'year': INTEGER}" if by_year else ""
        pattern = (folder / "**" / "*.parquet").as_posix().replace("'", "''")
        con.execute(
            f"CREATE VIEW silver_{name} AS "  # noqa: S608 - a local path, not user input
            f"SELECT * FROM read_parquet('{pattern}', hive_partitioning = true{types})"
        )
    return con


def build(silver: Path, out: Path, sql_dir: Path = SQL_DIR) -> dict[str, int]:
    """Run every query and write its table. Returns {table: rows}."""
    con = connect(silver)
    rows: dict[str, int] = {}
    for table, select in queries(sql_dir).items():
        con.execute(f"CREATE TABLE {table} AS {select}")
        folder = Path(out) / table
        folder.mkdir(parents=True, exist_ok=True)
        target = (folder / FILE_NAME).as_posix().replace("'", "''")
        con.execute(f"COPY {table} TO '{target}' (FORMAT parquet)")
        rows[table] = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608
    report(con)
    return rows


# What each table expected and what it observed, on the rows that summarise it.
_HEADLINES = {
    "gold_digit_frequency": (
        "chi-cuadrado de los dígitos (gl 9; crítico 16,919 al 5 %): pruebas, "
        "rechazos al 5 % y al 1 %",
        """SELECT game, count(*), count_if(rejects_05), count_if(rejects_01),
                  round(min(chi_square), 2), round(max(chi_square), 2)
           FROM (SELECT DISTINCT game, scope, position, digit_place, chi_square,
                        rejects_05, rejects_01 FROM gold_digit_frequency)
           GROUP BY game ORDER BY game""",
    ),
    "gold_quiniela_repeats": (
        "sorteos con un número repetido: sorteos, excluidos, observado, esperado, z",
        """SELECT game, draws, draws_excluded, round(observed_rate, 4), round(expected_rate, 4),
                  round(z_score, 2)
           FROM gold_quiniela_repeats WHERE scope = 'total' ORDER BY game""",
    ),
    "gold_tombola_replacements": (
        "reemplazos por sorteo: sorteos, excluidos, observado, esperado, según la Quiniela, z",
        """SELECT game, draws, draws_excluded, round(observed_mean, 4), round(expected_mean, 4),
                  round(implied_by_quiniela_mean, 4), round(z_score, 2)
           FROM gold_tombola_replacements WHERE scope = 'total' ORDER BY game""",
    ),
    "gold_5_de_oro_frequency": (
        "chi-cuadrado por rango y bolilla: sorteos, ajustado, gl, crítico 5 %, "
        "rechaza al 5 % y al 1 %",
        """SELECT DISTINCT rules_version, ball_type, draws, round(chi_square_adjusted, 2),
                  degrees_of_freedom, critical_05, rejects_05, rejects_01
           FROM gold_5_de_oro_frequency ORDER BY rules_version, ball_type""",
    ),
    "gold_pool_dynamics": (
        "el pozo sube si nadie ganó y baja si alguien ganó: comparados, como se esperaba, "
        "excluidos",
        """SELECT prize, count(as_expected), count_if(as_expected),
                  round(CAST(count_if(as_expected) AS double) / count(as_expected), 4),
                  count(excluded_reason)
           FROM gold_pool_dynamics GROUP BY prize ORDER BY prize""",
    ),
    "gold_punctuality": (
        "arranque a la hora: hora, sorteos, excluidos, a la hora, min a la 1.ª bolilla, "
        "duración media, mín y máx",
        """SELECT game, scheduled_start, draws, draws_excluded,
                  round(observed_on_schedule_rate, 4), round(mean_minutes_to_first_ball, 1),
                  round(mean_duration_minutes, 1), min_duration_minutes, max_duration_minutes
           FROM gold_punctuality WHERE scope = 'total' ORDER BY game""",
    ),
}


def report(con: duckdb.DuckDBPyConnection) -> None:
    for table, (title, sql) in _HEADLINES.items():
        print(f"\n{table} — {title}")
        for row in con.execute(sql).fetchall():
            print("  " + " · ".join("—" if v is None else str(v) for v in row))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--silver", type=Path, default=ROOT / "data" / "uy" / "silver")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "uy" / "gold")
    args = parser.parse_args(argv)
    try:
        rows = build(args.silver, args.out)
    except GoldError as error:
        print(f"uy-gold-local: {error}")
        return 1
    print()
    for table, count in rows.items():
        print(f"{table}: {count} filas → {args.out / table / FILE_NAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
