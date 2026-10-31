"""UY-027.2: ``uy-properties`` over fixture pages in a manifest of their own."""

from __future__ import annotations

import json
from datetime import date

import pytest
from test_uy_silver import Lake  # pytest puts this directory on sys.path

from sorteos.uy import properties, silver
from sorteos.uy.sources import ORO, QN, QV


@pytest.fixture
def lake(tmp_path):
    lake = Lake(tmp_path)
    yield lake
    lake.manifest.close()


def test_real_pages_give_the_counts_of_their_draws(lake):
    # Three real days, each picked for a count it moves. All three have a Vespertina and a
    # Nocturna (3 + 3); the two Wednesdays also have a 5 de Oro (2).
    # - 2006-08-31: the site published that Vespertina without its Tómbola, and it is kept
    #   that way (owner, UY-022), so it is the one Tómbola of size 0.
    # - 2006-12-06: the only 5 de Oro in the catalog with pozo_plata_equals_oro.
    # - 2016-07-06: a clean day after the first pozos PDF (2016-06-01). This lake has no PDF,
    #   so its 5 de Oro is the one draw number left null.
    lake.fixture("resultados", date(2006, 8, 31))
    lake.fixture("resultados", date(2006, 12, 6))
    lake.fixture("resultados", date(2016, 7, 6))
    report = properties.collect(lake.manifest, lake.bronze)

    assert report.draws == {QV: 3, QN: 3, ORO: 2}
    assert report.tombola_sizes == {0: 1, 20: 5}
    assert report.flags["pozo_plata_equals_oro"] == 1
    assert report.cross_source_check == {"not_checked": 8}  # no extracts in this lake
    assert report.draw_numbers == {"null": 1}  # 2016-07-06, and no pozos PDF read anywhere
    assert not report.failed
    text = properties.format_report(report)
    assert "draws: 8 (3 N, 3 V, 2 5 de Oro)" in text
    assert "tombola sizes: 1 with 0, 5 with 20" in text
    assert text.endswith("result: ok")


def test_quarantine_fails_the_run_and_says_why(lake, tmp_path, capsys):
    # main() applies the repo's manual_overrides: the 2019 strike pages are no_draw there,
    # never read, so the failure here is an extract that does not parse.
    day = date(2006, 8, 31)
    lake.fixture("resultados", day)
    lake.put("extracto_quiniela_vespertina", day, b"<html>not an extract</html>")
    lake.fixture("resultados", date(2016, 7, 6))
    lake.manifest.close()
    out = tmp_path / "properties.json"

    assert properties.main(["--root", str(tmp_path), "--json-report", str(out)]) == 1
    text = capsys.readouterr().err
    assert "quarantine: 1" in text
    assert "1  extracto_quiniela_vespertina: " in text
    assert text.endswith("result: FAILED (quarantine)\n")
    saved = json.loads(out.read_text())
    (reason,) = saved["quarantine"]
    assert reason.startswith("extracto_quiniela_vespertina: ")
    assert saved["draws"] == {QV: 1, QN: 2, ORO: 1}
    assert saved["tombola_sizes"] == {"20": 3}


def test_a_clean_bronze_exits_zero(lake, tmp_path):
    lake.fixture("resultados", date(2016, 7, 6))
    lake.manifest.close()
    assert properties.main(["--root", str(tmp_path)]) == 0


def test_an_empty_manifest_reports_nothing_and_passes(lake):
    report = properties.collect(lake.manifest, lake.bronze)
    assert report == properties.Report() and not report.failed
    text = properties.format_report(report)
    assert "quiniela with a repeated number: 0 of 0 (-)" in text
    assert "tombola replacements: -" in text


def draw(game, day, number=None, flags=()):
    return {
        "game": game,
        "draw_date": day,
        "cross_source_check": "match",
        "next_draw_text": None,
        "draw_number": number,
        "dq_flags": list(flags),
    }


def ball(game, day, ball_type, number, replacement=None):
    return {
        "game": game,
        "draw_date": day,
        "ball_type": ball_type,
        "number": number,
        "is_replacement": replacement,
    }


def test_repeats_replacements_and_the_draw_number_series_are_counted():
    day, oro = date(2025, 1, 6), date(2025, 1, 5)
    rows = silver.YearRows(
        draws=[
            draw(QN, day),
            draw(QV, day, flags=["tombola_not_from_quiniela"]),  # left out of P7
            draw(ORO, oro, 2800),
            draw(ORO, date(2025, 1, 8), 2801, ["draw_number_inferred"]),
            draw(ORO, date(2016, 5, 29)),  # before the first pozos PDF: not counted
        ],
        draw_numbers=[
            ball(QN, day, "quiniela", "1234"),
            ball(QN, day, "quiniela", "1234"),
            ball(QN, day, "tombola", "34", False),
            ball(QN, day, "tombola", "07", True),
            ball(QV, day, "tombola", "99", True),
        ],
    )
    report = properties.Report()
    report.add(rows)
    assert report.quiniela_with_repeats == 1
    assert report.tombola_sizes == {2: 1, 1: 1}
    assert (report.tombola_replacements, report.tombola_p7_draws) == (1, 1)
    assert report.draw_numbers == {"read": 1, "inferred": 1}
    assert report.flags == {"draw_number_inferred": 1, "tombola_not_from_quiniela": 1}
    assert report.without_next_draw == 5
    text = properties.format_report(report)
    assert "quiniela with a repeated number: 1 of 2 (50.0 %)" in text
    assert "tombola replacements: 1.000 per draw, over 1 (P7)" in text
    assert "5 de Oro draw number since the first pozos PDF: 1 inferred, 1 read" in text
