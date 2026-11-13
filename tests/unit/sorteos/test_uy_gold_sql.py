"""UY gold (UY-032, UY-044.2): the six SELECTs of sql/uy/gold/ and scripts/uy_gold_local.py.

Each query runs in DuckDB over a small synthetic silver, written with silver's own schemas, and
every number it gives is computed again here in plain Python, from the same rows. The SQL is
written for Athena; that both engines agree on the real data is checked against Athena itself
(the PR records it), which a unit test cannot do.
"""

from __future__ import annotations

import importlib.util
import math
import random
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from sorteos.core import silver

REPO = Path(__file__).parents[3]
SQL_DIR = REPO / "sql" / "uy" / "gold"
QUINIELAS = ("quiniela_nocturna", "quiniela_vespertina")
START = {"quiniela_vespertina": (15, 0), "quiniela_nocturna": (21, 0)}
NOW = datetime(2026, 11, 11, 12, 0, 0)
TABLES = (
    "gold_digit_frequency",
    "gold_quiniela_repeats",
    "gold_tombola_replacements",
    "gold_5_de_oro_frequency",
    "gold_pool_dynamics",
    "gold_punctuality",
)


def _script():
    path = REPO / "scripts" / "uy_gold_local.py"
    spec = importlib.util.spec_from_file_location("uy_gold_local", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gold = _script()


# --- a synthetic silver ----------------------------------------------------------------------


def _row(spec: silver.Table, **values) -> dict:
    base = {"operator": "dnlq", "ingested_at": NOW, "run_id": "test"}
    row = {f.name: None for f in spec.file_schema}
    row.update({k: v for k, v in base.items() if k in row})
    row.update(values)
    return row


def _write(root: Path, spec: silver.Table, rows: list[dict]) -> None:
    """One file per partition, with the table's file schema: what the silver writer leaves."""
    parts: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        row = dict(row)
        path = [f"{name}={row.pop(name)}" for name in spec.partition]
        if spec.year_of:
            path.append(f"year={row[spec.year_of].year}")
        parts[tuple(path)].append(row)
    for path, part in parts.items():
        folder = root.joinpath(spec.name, *path)
        folder.mkdir(parents=True)
        pq.write_table(
            pa.Table.from_pylist(part, schema=spec.file_schema), folder / "part-0.parquet"
        )


def _quiniela_draws(rng: random.Random) -> list[dict]:
    """120 draws per game over two years. Draws 0-2 of each game are the special ones."""
    draws = []
    for game in QUINIELAS:
        hour, minute = START[game]
        for i in range(120):
            day = date(2024, 1, 1) + timedelta(days=i * 6)
            numbers = [f"{rng.randrange(1000):03d}" for _ in range(20)]
            if i % 7 == 0:
                numbers[19] = numbers[3]  # a repeat for sure
            seen: set[str] = set()
            tombola = []
            for number in numbers:
                tombola.append((number[1:], number[1:] in seen))
                seen.add(number[1:])
            late = 30 if i % 10 == 4 else 0
            started = datetime(day.year, day.month, day.day, hour, minute) + timedelta(minutes=late)
            draws.append(
                {
                    "game": game,
                    "date": day,
                    "numbers": numbers,
                    "tombola": tombola,
                    "flags": [],
                    "started": started,
                    "first": started + timedelta(minutes=rng.randrange(5, 15)),
                    "ended": started + timedelta(minutes=rng.randrange(17, 30)),
                }
            )
        mine = [d for d in draws if d["game"] == game]
        mine[0]["flags"] = ["tombola_repeated_number"]
        mine[0]["tombola"] = [(n, None) for n, _ in mine[0]["tombola"]]
        mine[1]["tombola"] = []  # a Quiniela without a Tómbola (2006-08-31)
        mine[2]["flags"] = ["timing_out_of_order"]
        mine[2]["ended"] = mine[2]["started"] - timedelta(minutes=300)
        mine[5]["ended"] = mine[5]["started"] + timedelta(minutes=400)  # a typed-wrong hour
    return draws


def _oro_draws(rng: random.Random) -> list[dict]:
    """60 draws under 01-44 and 80 under 01-48, with the pools of each."""
    draws = []
    pools = {
        "oro": Decimal("1000000.00"),
        "plata": Decimal("50000.00"),
        "revancha": Decimal("700000.00"),
    }
    for i in range(140):
        size = 44 if i < 60 else 48
        day = (date(2013, 6, 2) if i < 60 else date(2014, 3, 19)) + timedelta(
            days=(i if i < 60 else i - 60) * 4
        )
        oro = sorted(rng.sample(range(1, size + 1), 5))
        extra = rng.choice([n for n in range(1, size + 1) if n not in oro])
        prizes = {}
        for prize in pools:
            coupons = rng.choice([0, 0, 0, 1, 2])
            prizes[prize] = {"amount": pools[prize], "coupons": coupons, "flags": []}
            # Mostly as the hypothesis says, with exceptions so `as_expected` has both values.
            grows = (coupons == 0) != (rng.random() < 0.1)
            step = Decimal(rng.randrange(1, 9) * 1000)
            pools[prize] = (
                pools[prize] + step if grows else max(pools[prize] - step, Decimal("100.00"))
            )
        draws.append(
            {
                "date": day,
                "oro": oro,
                "extra": extra,
                "revancha": sorted(rng.sample(range(1, size + 1), 5)),
                "prizes": prizes,
            }
        )
    draws[10]["prizes"]["plata"]["flags"] = ["pozo_plata_equals_oro"]
    draws[20]["prizes"]["oro"]["amount"] = None  # an empty cell
    draws[20]["prizes"]["oro"]["coupons"] = None
    draws[30]["prizes"]["revancha"]["coupons"] = None  # winners unknown, amount there
    draws[40]["prizes"]["revancha"]["flags"] = ["amount_sources_differ"]
    draws[51]["prizes"]["oro"]["amount"] = draws[50]["prizes"]["oro"]["amount"]  # 'same'
    return draws


def _status(coupons: int | None) -> str:
    return "unknown" if coupons is None else ("winners" if coupons else "no_winners")


@pytest.fixture(scope="module")
def data(tmp_path_factory) -> dict:
    rng = random.Random(44)
    root = tmp_path_factory.mktemp("silver")
    quinielas, oros = _quiniela_draws(rng), _oro_draws(rng)
    draws, numbers, prizes = [], [], []
    for d in quinielas:
        key = {"country": "uy", "game": d["game"], "draw_date": d["date"]}
        draws.append(
            _row(
                silver.DRAWS,
                **key,
                started_local=d["started"],
                first_ball_local=d["first"],
                ended_local=d["ended"],
                timezone="America/Montevideo",
                cross_source_check="match",
                dq_flags=d["flags"],
            )
        )
        for position, number in enumerate(d["numbers"], 1):
            numbers.append(
                _row(silver.DRAW_NUMBERS, **key, ball_type="quiniela", position=position,
                     is_draw_order=True, number=number)
            )  # fmt: skip
        for position, (number, replacement) in enumerate(
            sorted(d["tombola"], key=lambda t: t[0]), 1
        ):
            numbers.append(
                _row(silver.DRAW_NUMBERS, **key, ball_type="tombola", position=position,
                     is_draw_order=False, number=number, is_replacement=replacement)
            )  # fmt: skip
    # One Vespertina whose times were never published: excluded from punctuality.
    draws[-1].update(started_local=None, first_ball_local=None, ended_local=None)
    quinielas[-1]["started"] = None
    for d in oros:
        key = {"country": "uy", "game": "5_de_oro", "draw_date": d["date"]}
        draws.append(
            _row(
                silver.DRAWS,
                **key,
                timezone="America/Montevideo",
                cross_source_check="match",
                dq_flags=[],
            )
        )
        balls = [("oro", d["oro"]), ("extra", [d["extra"]]), ("revancha", d["revancha"])]
        for ball_type, values in balls:
            for position, number in enumerate(values, 1):
                numbers.append(
                    _row(silver.DRAW_NUMBERS, **key, ball_type=ball_type, position=position,
                         is_draw_order=False, number=f"{number:02d}")
                )  # fmt: skip
        for prize, p in d["prizes"].items():
            prizes.append(
                _row(silver.PRIZES, **key, prize=prize, pool_amount=p["amount"], currency="UYU",
                     winners_status=_status(p["coupons"]), winning_coupons=p["coupons"],
                     dq_flags=p["flags"])
            )  # fmt: skip
    rules = [
        _row(silver.GAME_RULES, country="uy", game="5_de_oro", rule="rango_numeros", value="01-44",
             valid_from=date(2006, 8, 16), valid_to=date(2014, 3, 18)),
        _row(silver.GAME_RULES, country="uy", game="5_de_oro", rule="rango_numeros", value="01-48",
             valid_from=date(2014, 3, 19)),
        _row(silver.GAME_RULES, country="uy", game="5_de_oro", rule="precio_5_de_oro", value="$ 20",
             valid_from=date(2014, 3, 19)),
    ]  # fmt: skip
    _write(root, silver.DRAWS, draws)
    _write(root, silver.DRAW_NUMBERS, numbers)
    _write(root, silver.PRIZES, prizes)
    _write(root, silver.GAME_RULES, rules)
    return {"root": root, "quinielas": quinielas, "oros": oros}


@pytest.fixture(scope="module")
def built(data, tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("gold")
    rows = gold.build(data["root"], out)
    tables = {name: pq.read_table(out / name / "part-0.parquet").to_pylist() for name in rows}
    return {"rows": rows, "tables": tables, "out": out}


def _only(rows: list[dict], **where) -> list[dict]:
    return [r for r in rows if all(r[k] == v for k, v in where.items())]


def _one(rows: list[dict], **where) -> dict:
    found = _only(rows, **where)
    assert len(found) == 1, (where, len(found))
    return found[0]


# --- the files and the runner ----------------------------------------------------------------


def test_one_file_per_table_in_order():
    assert tuple(gold.queries()) == TABLES


@pytest.mark.parametrize("table", TABLES)
def test_every_file_is_one_select_that_says_what_it_expects(table):
    path = next(SQL_DIR.glob(f"*_{table}.sql"))
    text = path.read_text("utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.startswith("--"))
    assert body.lstrip().upper().startswith(("WITH", "SELECT"))
    assert ";" not in body  # one statement: the builder wraps it in a CTAS (UY-044.3)
    upper = body.upper()
    for word in ("CREATE ", "INSERT ", "DROP ", "EXTERNAL_LOCATION"):
        assert word not in upper
    header = text[: text.index(body.lstrip()[:20])]
    for word in ("Grain:", "Expected:", "Observed:", "Exclude"):
        assert word in header, f"{path.name} header lacks {word}"


@pytest.mark.parametrize("table", TABLES)
def test_no_function_that_athena_and_duckdb_read_differently(table):
    """The probe of 2026-11-11 on real silver (sql/uy/gold/README.md)."""
    body = "\n".join(
        line
        for line in next(SQL_DIR.glob(f"*_{table}.sql")).read_text("utf-8").splitlines()
        if not line.startswith("--")
    ).lower()
    for banned in (
        "day_of_week",
        "date_add(",
        "approx_percentile",
        "sequence(",
        "generate_series",
        "range(",
    ):
        assert banned not in body
    # Only silver is read, and unqualified: the database comes from the connection.
    assert "lottery_uy_db." not in body
    assert not {"silver_quarantine", "raw"} & set(body.replace("(", " ").split())


def test_build_writes_one_parquet_per_table(built):
    assert tuple(built["rows"]) == TABLES
    for table, count in built["rows"].items():
        assert count > 0
        assert pq.read_metadata(built["out"] / table / "part-0.parquet").num_rows == count


def test_year_is_read_as_the_catalogs_int(data):
    con = gold.connect(data["root"])
    kind = con.execute("SELECT typeof(year) FROM silver_draws LIMIT 1").fetchone()[0]
    assert kind == "INTEGER"
    # A table with no files has no view, so a query over it fails instead of counting nothing.
    with pytest.raises(duckdb.CatalogException):
        con.execute("SELECT count(*) FROM silver_quarantine")


def test_runner_errors(tmp_path):
    with pytest.raises(gold.GoldError, match="no silver"):
        gold.connect(tmp_path / "nowhere")
    (tmp_path / "bad.sql").write_text("SELECT 1", "utf-8")
    with pytest.raises(gold.GoldError, match="expected NN_gold"):
        gold.queries(tmp_path)
    (tmp_path / "bad.sql").unlink()
    with pytest.raises(gold.GoldError, match="no SQL files"):
        gold.queries(tmp_path)
    (tmp_path / "01_gold_x.sql").write_text("  ;\n", "utf-8")
    with pytest.raises(gold.GoldError, match="empty"):
        gold.queries(tmp_path)
    assert gold.main(["--silver", str(tmp_path / "nowhere"), "--out", str(tmp_path / "out")]) == 1


def test_main_builds_and_reports(data, tmp_path, capsys):
    assert gold.main(["--silver", str(data["root"]), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    for table in TABLES:
        assert f"{table}: " in out and f"{table} — " in out


# --- the constants ---------------------------------------------------------------------------


def test_expected_repeat_rate_is_the_birthday_problem(built):
    none = math.prod(1 - i / 1000 for i in range(20))
    for row in built["tables"]["gold_quiniela_repeats"]:
        assert row["expected_rate"] == pytest.approx(1 - none, abs=1e-15)


def test_critical_values_are_the_chi_square_distributions(built):
    chi2 = pytest.importorskip("scipy.stats").chi2
    rows = built["tables"]["gold_digit_frequency"] + built["tables"]["gold_5_de_oro_frequency"]
    seen = set()
    for row in rows:
        df = row["degrees_of_freedom"]
        seen.add(df)
        assert row["critical_05"] == pytest.approx(chi2.ppf(0.95, df), abs=5e-4)
        assert row["critical_01"] == pytest.approx(chi2.ppf(0.99, df), abs=5e-4)
    assert seen == {9, 43, 47}


# --- gold_digit_frequency --------------------------------------------------------------------


def test_digit_frequency(data, built):
    rows = built["tables"]["gold_digit_frequency"]
    assert len(rows) == 2 * 3 * 21 * 10  # every digit of every group, seen or not
    places = {"hundreds": 0, "tens": 1, "units": 2}
    for game in QUINIELAS:
        draws = [d for d in data["quinielas"] if d["game"] == game]
        for place, index in places.items():
            for position in (None, 1, 13, 20):
                numbers = [
                    n for d in draws for p, n in enumerate(d["numbers"], 1) if position in (None, p)
                ]
                counts = Counter(n[index] for n in numbers)
                expected = len(numbers) / 10
                chi = sum((counts[str(k)] - expected) ** 2 / expected for k in range(10))
                scope = "total" if position is None else "position"
                group = _only(rows, game=game, scope=scope, position=position, digit_place=place)
                assert [r["digit"] for r in group] == [str(k) for k in range(10)]
                for r in group:
                    assert r["observed"] == counts[r["digit"]]
                    assert r["numbers"] == len(numbers)
                    assert r["expected"] == pytest.approx(expected)
                    assert r["observed_share"] == pytest.approx(counts[r["digit"]] / len(numbers))
                    assert r["chi_square"] == pytest.approx(chi)
                    assert r["rejects_05"] == (chi > 16.919)
                    assert r["rejects_01"] == (chi > 21.666)


def _quiniela_number(day: date, position: int, number: str) -> dict:
    return _row(
        silver.DRAW_NUMBERS,
        country="uy",
        game="quiniela_nocturna",
        draw_date=day,
        ball_type="quiniela",
        position=position,
        is_draw_order=True,
        number=number,
    )


def test_a_digit_that_never_came_out_is_a_row_with_zero(tmp_path):
    rows = [_quiniela_number(date(2026, 1, 2), p, "111") for p in range(1, 21)]
    _write(tmp_path, silver.DRAW_NUMBERS, rows)
    con = gold.connect(tmp_path)
    sql = gold.queries()["gold_digit_frequency"]
    got = con.execute(
        "SELECT digit, observed, chi_square, rejects_01 "
        f"FROM ({sql}) "  # noqa: S608
        "WHERE scope = 'total' AND digit_place = 'tens' ORDER BY digit"
    ).fetchall()
    assert [(d, o) for d, o, _, _ in got] == [(str(k), 20 if k == 1 else 0) for k in range(10)]
    assert got[0][2] == pytest.approx(180.0) and got[0][3] is True  # 9 x 2 + 18^2 / 2


# --- gold_quiniela_repeats -------------------------------------------------------------------


def test_quiniela_repeats(data, built):
    rows = built["tables"]["gold_quiniela_repeats"]
    expected = 1 - math.prod(1 - i / 1000 for i in range(20))
    for game in QUINIELAS:
        for year in (None, 2024, 2025):
            draws = [
                d for d in data["quinielas"] if d["game"] == game and year in (None, d["date"].year)
            ]
            repeats = sum(len(set(d["numbers"])) < 20 for d in draws)
            row = _one(rows, game=game, scope="total" if year is None else "year", year=year)
            assert (row["draws"], row["draws_excluded"], row["draws_with_repeat"]) == (
                len(draws),
                0,
                repeats,
            )
            assert row["observed_rate"] == pytest.approx(repeats / len(draws))
            error = math.sqrt(expected * (1 - expected) / len(draws))
            assert row["standard_error"] == pytest.approx(error)
            assert row["z_score"] == pytest.approx((repeats / len(draws) - expected) / error)
    assert _one(rows, game=QUINIELAS[0], scope="total", year=None)["draws_with_repeat"] >= 18


def test_a_draw_without_20_numbers_is_excluded_and_counted(tmp_path):
    def draw(day: int, count: int) -> list[dict]:
        return [_quiniela_number(date(2026, 1, day), p, f"{p:03d}") for p in range(1, count + 1)]

    _write(tmp_path, silver.DRAW_NUMBERS, draw(1, 20) + draw(2, 19))
    con = gold.connect(tmp_path)
    sql = gold.queries()["gold_quiniela_repeats"]
    got = con.execute(
        f"SELECT draws, draws_excluded, draws_with_repeat FROM ({sql}) "  # noqa: S608
        "WHERE scope = 'total'"
    ).fetchall()
    assert got == [(1, 1, 0)]


# --- gold_tombola_replacements ---------------------------------------------------------------


def test_tombola_replacements(data, built):
    rows = built["tables"]["gold_tombola_replacements"]
    expected = 20 - 100 * (1 - 0.99**20)
    for game in QUINIELAS:
        for year in (None, 2024, 2025):
            draws = [
                d for d in data["quinielas"] if d["game"] == game and year in (None, d["date"].year)
            ]
            usable = [
                d
                for d in draws
                if d["tombola"] and not d["flags"][:1] == ["tombola_repeated_number"]
            ]
            counts = [sum(bool(flag) for _, flag in d["tombola"]) for d in usable]
            implied = [20 - len({n[1:] for n in d["numbers"]}) for d in usable]
            row = _one(rows, game=game, scope="total" if year is None else "year", year=year)
            assert (row["draws"], row["draws_excluded"]) == (len(usable), len(draws) - len(usable))
            assert row["replacements"] == sum(counts)
            mean = sum(counts) / len(counts)
            assert row["observed_mean"] == pytest.approx(mean)
            assert row["expected_mean"] == pytest.approx(expected)
            # The marks and the Quiniela's own endings must tell the same story.
            assert row["implied_by_quiniela_mean"] == pytest.approx(sum(implied) / len(implied))
            assert row["implied_by_quiniela_mean"] == pytest.approx(row["observed_mean"])
            deviation = math.sqrt(sum((c - mean) ** 2 for c in counts) / (len(counts) - 1))
            error = deviation / math.sqrt(len(counts))
            assert row["standard_error"] == pytest.approx(error)
            assert row["z_score"] == pytest.approx((mean - expected) / error)
    total = _one(rows, game=QUINIELAS[0], scope="total", year=None)
    assert total["draws_excluded"] == 2  # the flagged one and the one without a Tómbola


# --- gold_5_de_oro_frequency -----------------------------------------------------------------


def test_5_de_oro_frequency(data, built):
    rows = built["tables"]["gold_5_de_oro_frequency"]
    assert len(rows) == 3 * 44 + 3 * 48
    for version, size, critical in (
        ("01-44", 44, (59.304, 67.459)),
        ("01-48", 48, (64.001, 72.443)),
    ):
        draws = [d for d in data["oros"] if (d["date"] < date(2014, 3, 19)) == (size == 44)]
        for ball_type, per_draw in (("oro", 5), ("extra", 1), ("revancha", 5)):
            balls = [
                n for d in draws for n in ([d["extra"]] if ball_type == "extra" else d[ball_type])
            ]
            counts = Counter(balls)
            expected = len(balls) / size
            chi = sum((counts[n] - expected) ** 2 / expected for n in range(1, size + 1))
            adjusted = chi * (size - 1) / (size - per_draw)
            group = _only(rows, rules_version=version, ball_type=ball_type)
            assert [r["number"] for r in group] == [f"{n:02d}" for n in range(1, size + 1)]
            for r in group:
                assert r["game"] == "5_de_oro"
                assert r["draws"] == len(draws)
                assert r["observed"] == counts[int(r["number"])]
                assert r["expected"] == pytest.approx(expected)
                assert r["chi_square"] == pytest.approx(chi)
                assert r["chi_square_adjusted"] == pytest.approx(adjusted)
                assert r["degrees_of_freedom"] == size - 1
                assert (r["critical_05"], r["critical_01"]) == critical
                assert r["rejects_05"] == (adjusted > critical[0])
                assert r["rejects_01"] == (adjusted > critical[1])
    first = _one(rows, rules_version="01-44", ball_type="oro", number="01")
    assert (first["valid_from"], first["valid_to"]) == (date(2006, 8, 16), date(2014, 3, 18))
    assert _one(rows, rules_version="01-48", ball_type="oro", number="48")["valid_to"] is None


# --- gold_pool_dynamics ----------------------------------------------------------------------


def test_pool_dynamics(data, built):
    rows = built["tables"]["gold_pool_dynamics"]
    assert len(rows) == 140 * 3  # every published pool stays, the excluded ones too
    both = set()
    for prize in ("oro", "plata", "revancha"):
        previous = None
        for d in data["oros"]:
            p = d["prizes"][prize]
            row = _one(rows, draw_date=d["date"], prize=prize)
            assert row["pool_amount"] == p["amount"]
            assert row["winning_coupons"] == p["coupons"]
            reason = p["flags"][0] if p["flags"] else ("no_amount" if p["amount"] is None else None)
            assert row["excluded_reason"] == reason
            if reason:
                for column in ("previous_draw_date", "pool_change", "expected_direction",
                               "observed_direction", "as_expected"):  # fmt: skip
                    assert row[column] is None
                continue  # and the next row is compared with the last usable one
            if previous is None:
                assert row["previous_draw_date"] is None and row["as_expected"] is None
            else:
                day, amount, coupons = previous
                assert row["previous_draw_date"] == day
                assert row["previous_pool_amount"] == amount
                assert row["previous_winners_status"] == _status(coupons)
                assert row["pool_change"] == p["amount"] - amount
                expected = None if coupons is None else ("down" if coupons else "up")
                change = p["amount"] - amount
                observed = "up" if change > 0 else ("down" if change < 0 else "same")
                assert row["expected_direction"] == expected
                assert row["observed_direction"] == observed
                assert row["as_expected"] == (None if expected is None else expected == observed)
                both.add(row["as_expected"])
            previous = (d["date"], p["amount"], p["coupons"])
    assert both == {True, False, None}
    assert Counter(r["excluded_reason"] for r in rows if r["excluded_reason"]) == {
        "pozo_plata_equals_oro": 1,
        "no_amount": 1,
        "amount_sources_differ": 1,
    }
    assert "same" in {r["observed_direction"] for r in rows}


# --- gold_punctuality ------------------------------------------------------------------------


def test_punctuality(data, built):
    rows = built["tables"]["gold_punctuality"]
    for game in QUINIELAS:
        hour, minute = START[game]
        for year in (None, 2024, 2025):
            draws = [
                d for d in data["quinielas"] if d["game"] == game and year in (None, d["date"].year)
            ]
            usable = [d for d in draws if d["started"] and "timing_out_of_order" not in d["flags"]]
            offsets = [
                d["started"].hour * 60 + d["started"].minute - hour * 60 - minute for d in usable
            ]
            first = [(d["first"] - d["started"]).total_seconds() / 60 for d in usable]
            duration = [int((d["ended"] - d["started"]).total_seconds() // 60) for d in usable]
            row = _one(rows, game=game, scope="total" if year is None else "year", year=year)
            assert row["scheduled_start"] == f"{hour:02d}:{minute:02d}"
            assert (row["draws"], row["draws_excluded"]) == (len(usable), len(draws) - len(usable))
            assert row["draws_on_schedule"] == offsets.count(0)
            assert row["observed_on_schedule_rate"] == pytest.approx(offsets.count(0) / len(usable))
            assert row["expected_on_schedule_rate"] == 1.0
            assert row["mean_start_offset_minutes"] == pytest.approx(sum(offsets) / len(usable))
            assert row["mean_minutes_to_first_ball"] == pytest.approx(sum(first) / len(usable))
            assert row["mean_duration_minutes"] == pytest.approx(sum(duration) / len(usable))
            assert (row["min_duration_minutes"], row["max_duration_minutes"]) == (
                min(duration),
                max(duration),
            )
            assert row["draws_over_60_minutes"] == sum(m > 60 for m in duration)
    night = _one(rows, game="quiniela_nocturna", scope="total", year=None)
    assert night["draws_excluded"] == 1 and night["max_duration_minutes"] == 400
    # The Vespertina also lost the draw whose times were never published.
    assert _one(rows, game="quiniela_vespertina", scope="total", year=None)["draws_excluded"] == 2
    assert not _only(rows, game="5_de_oro")
