"""UY-030.2: the site's own counts — what is asked, how it is kept, how it is compared."""

from __future__ import annotations

import json
from datetime import date

import pytest
from test_uy_backfill import root_logger_restored  # noqa: F401 (a fixture)
from test_uy_http_client import FakeSession, response
from test_uy_parser_estadisticas import page
from test_uy_reconcile import RUN, d, draw

from sorteos.core import silver as core_silver
from sorteos.core.bronze import BronzeStore
from sorteos.uy import backfill, estadisticas, privacy
from sorteos.uy import dq_flags as dq
from sorteos.uy.sources import COUNTRY, ORO, QN, QV

ORO_URL = "https://www.loteria.gub.uy/ver_estadisticas.php?xjue=4&xpos=1"
FETCHED = date(2026, 11, 1)


def ball(game, day, ball_type, position, number):
    return {
        "country": COUNTRY,
        "operator": "dnlq",
        "game": game,
        "draw_date": d(day),
        "ball_type": ball_type,
        "position": position,
        "is_draw_order": True,
        "number": number,
        "is_replacement": None,
        "ingested_at": RUN.ingested_at,
        "run_id": RUN.run_id,
        "source_key": f"resultados_{day}.html",
        "source_sha256": "a" * 64,
        "parser_version": "resultados:1",
    }


# Two 5 de Oro draws around the site's known error: the Revancha of 2010-11-07 is also stored
# under 2010-10-07 (FINDINGS, Q10), so the site counts its 5 numbers twice.
ORO_DRAWS = [draw("2010-10-03", "2010-10-06"), draw("2010-11-07", "2010-11-10")]
REVANCHA = ("06", "08", "13", "40", "44")
ORO_BALLS = [
    *(
        ball(ORO, "2010-10-03", "oro", i, n)
        for i, n in enumerate(("01", "02", "03", "04", "05"), 1)
    ),
    *(ball(ORO, "2010-10-03", "revancha", i, n) for i, n in enumerate(REVANCHA, 1)),
    *(
        ball(ORO, "2010-11-07", "oro", i, n)
        for i, n in enumerate(("01", "02", "03", "04", "48"), 1)
    ),
    *(ball(ORO, "2010-11-07", "revancha", i, n) for i, n in enumerate(REVANCHA, 1)),
    ball(ORO, "2010-11-07", "extra", 1, "17"),  # never counted by the site
]


def oro_page(revancha_times=3, **changes):
    oro = {"01": 2, "02": 2, "03": 2, "04": 2, "05": 1, "48": 1, **changes}
    cells = ["5 de Oro", "Número", "Veces", *(x for n, t in oro.items() for x in (n, str(t)))]
    cells += ["Revancha", *(x for n in REVANCHA for x in (n, str(revancha_times)))]
    return page(*cells, consulted=2 * 2 + 1)


def write_silver(root, draws=ORO_DRAWS, balls=ORO_BALLS):
    for table, rows in ((core_silver.DRAWS, draws), (core_silver.DRAW_NUMBERS, balls)):
        for year in sorted({r["draw_date"].year for r in rows}):
            core_silver.write(
                root,
                table,
                [r for r in rows if r["draw_date"].year == year],
                country=COUNTRY,
                year=year,
                flags=dq.CATALOG,
            )


def keep(tmp_path, content: bytes, fetched=FETCHED, last=date(2010, 11, 7)):
    """One 5 de Oro answer kept in bronze, as fetch() keeps it."""
    session = FakeSession({ORO_URL: [response(200, content)]})
    client = privacy.polite_client(session=session, sleep=lambda _s: None)
    bronze = BronzeStore(tmp_path / "root", COUNTRY)
    return bronze, estadisticas.fetch(client, bronze, estadisticas.queries({ORO: last}), fetched)


# --- what is asked ---------------------------------------------------------------------


def test_twelve_queries_with_only_values_the_form_offers():
    asked = estadisticas.queries({ORO: d("2026-10-28"), QV: d("2026-10-30"), QN: d("2026-10-30")})
    assert [q.name for q in asked] == [
        "5_de_oro",
        *(f"quiniela_pos{p:02d}-{p:02d}" for p in (1, 2, 3, 4, 5, 6, 10, 15, 20)),
        "quiniela_pos01-20",
        "tombola",
    ]
    oro, first, *_, tombola = asked
    assert oro.url == ORO_URL
    assert oro.form == {
        "xdia": "1",
        "xmes": "01",
        "xano": "2006",
        "hdia": "28",
        "hmes": "10",
        "hano": "2026",
    }
    assert first.form["xdes"] == first.form["xhas"] == "1"
    assert (first.game, first.start, first.end) == (QV, d("2007-01-01"), d("2026-10-30"))
    assert tombola.url.endswith("xjue=3&xpos=1") and "xdes" not in tombola.form
    assert estadisticas.queries({QN: d("2026-10-30")}) == []  # the Nocturna has no form


# --- bronze ------------------------------------------------------------------------------


def test_fetch_keeps_each_answer_as_served_and_an_index_of_what_was_asked(tmp_path):
    content = oro_page()
    bronze, index = keep(tmp_path, content)
    (row,) = index
    prefix = f"bronze/country=uy/source=estadisticas/fetched={FETCHED}"
    assert row["bronze_key"] == f"{prefix}/5_de_oro.html"
    assert bronze.read(row["bronze_key"]) == content
    assert (row["xjue"], row["status"], row["bytes"]) == (4, 200, len(content))
    assert json.loads(bronze.read(f"{prefix}/queries.json")) == index


def test_latest_reads_the_newest_set_that_has_its_index(tmp_path):
    bronze, _ = keep(tmp_path, oro_page(revancha_times=1), fetched=date(2026, 10, 1))
    keep(tmp_path, oro_page(), fetched=date(2026, 11, 1))
    half = tmp_path / "root" / "bronze/country=uy/source=estadisticas/fetched=2026-12-01"
    half.mkdir()  # a run cut before its index: not a set
    fetched, (answer,) = estadisticas.latest(bronze)
    assert fetched == "2026-11-01"
    assert answer.stats.grids["Revancha"]["06"] == 3
    assert answer.query == estadisticas.queries({ORO: date(2010, 11, 7)})[0]


def test_latest_without_any_set_is_none(tmp_path):
    assert estadisticas.latest(BronzeStore(tmp_path, COUNTRY)) is None


def test_a_changed_or_unreadable_answer_is_an_error_not_a_count(tmp_path):
    bronze, (row,) = keep(tmp_path, b"<html>Mantenimiento</html>")
    (answer,) = estadisticas.latest(bronze)[1]
    assert answer.error == "no 'Cantidad de sorteos consultados'"
    bronze.write(row["bronze_key"], oro_page())
    (answer,) = estadisticas.latest(bronze)[1]
    assert answer.error == "bronze is not what was fetched"


# --- the comparison ------------------------------------------------------------------------


def compared(tmp_path, content, status=200):
    write_silver(tmp_path / "silver")
    bronze, _ = keep(tmp_path, content)
    if status != 200:
        index_key = f"bronze/country=uy/source=estadisticas/fetched={FETCHED}/queries.json"
        index = json.loads(bronze.read(index_key))
        index[0]["status"] = status
        bronze.write(index_key, json.dumps(index).encode())
    (c,) = estadisticas.compare_latest(bronze, tmp_path / "silver")[1]
    return c


def test_silver_matches_the_site_once_the_known_revancha_is_added(tmp_path):
    c = compared(tmp_path, oro_page())
    assert c.ok
    assert c.consulted == (5, 5)
    assert [k.day for k in c.known] == [date(2010, 10, 7)]
    assert c.numbers == 10 + 15
    assert estadisticas.describe(c) == [
        "5_de_oro (2006-01-01 to 2010-11-07, all): 5 draws consulted (silver 5), 25 numbers, ok",
        "  known: 2010-10-07 revancha 06 08 13 40 44 "
        "(FINDINGS Q10: the Revancha of 2010-11-07 also stored under 2010-10-07)",
    ]


def test_a_count_silver_does_not_have_is_a_difference(tmp_path):
    c = compared(tmp_path, oro_page(revancha_times=2, **{"05": 2}))
    assert not c.ok
    assert c.differences["oro"] == {"05": (2, 1)}
    assert c.differences["revancha"] == {n: (2, 3) for n in REVANCHA}
    assert "  oro 05: site 2, silver 1" in estadisticas.describe(c)


def test_an_answer_that_is_not_200_is_an_error(tmp_path):
    c = compared(tmp_path, oro_page(), status=500)
    assert (c.ok, c.error) == (False, "HTTP 500")
    assert estadisticas.describe(c) == ["5_de_oro (2006-01-01 to 2010-11-07, all): HTTP 500"]


def test_the_quiniela_counts_only_the_positions_asked_and_only_the_vespertina():
    q = estadisticas.queries({QV: d("2025-12-31")})[0]  # position 1
    answer = estadisticas.Answer(
        q,
        200,
        estadisticas.parser.Stats(1, {"": estadisticas.Counter({"073": 1})}),
    )
    draws = [
        {"game": QV, "draw_date": d("2025-01-06")},
        {"game": QN, "draw_date": d("2025-01-06")},
    ]
    numbers = [
        ball(QV, "2025-01-06", "quiniela", 1, "073"),
        ball(QV, "2025-01-06", "quiniela", 2, "500"),  # another position
        ball(QV, "2025-01-06", "tombola", 1, "73"),  # another ball
        ball(QN, "2025-01-06", "quiniela", 1, "999"),  # the Nocturna
        ball(QV, "2006-12-29", "quiniela", 1, "111"),  # before the range
    ]
    c = estadisticas.compare(answer, draws, numbers)
    assert c.ok and c.consulted == (1, 1) and c.known == []
    assert estadisticas.describe(c)[0].startswith("quiniela_pos01-01 (2007-01-01 to 2025-12-31,")
    assert "positions 1-1" in estadisticas.describe(c)[0]


def test_last_draws_per_game(tmp_path):
    write_silver(tmp_path)
    assert estadisticas.last_draws(tmp_path) == {ORO: d("2010-11-07")}


# --- the command ---------------------------------------------------------------------------


@pytest.mark.usefixtures("root_logger_restored")
def test_main_asks_keeps_and_compares(tmp_path, monkeypatch, capsys):
    write_silver(tmp_path / "silver")
    session = FakeSession({ORO_URL: [response(200, oro_page())]})
    real = privacy.polite_client
    monkeypatch.setattr(privacy, "polite_client", lambda: real(session=session, sleep=lambda _s: 0))
    monkeypatch.setattr(backfill, "today_in_uruguay", lambda: FETCHED)
    argv = ["--root", str(tmp_path / "root"), "--silver", str(tmp_path / "silver")]
    assert estadisticas.main(argv) == 0
    assert "25 numbers, ok" in capsys.readouterr().err
    assert (tmp_path / "root" / estadisticas.set_prefix(FETCHED) / "queries.json").is_file()

    session.answers[ORO_URL] = [response(200, oro_page(revancha_times=9))]
    assert estadisticas.main(argv) == 1


@pytest.mark.usefixtures("root_logger_restored")
def test_main_with_empty_silver_asks_nothing(tmp_path, capsys):
    assert estadisticas.main(["--root", str(tmp_path), "--silver", str(tmp_path / "s")]) == 1
    assert "silver is empty: nothing to ask" in capsys.readouterr().err
