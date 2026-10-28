"""UY-025.2: bronze pages to silver rows, with the real fixtures in a manifest of their own."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from sorteos.core import manifest as mf
from sorteos.core.bronze import BronzeStore
from sorteos.uy import dq_flags as dq
from sorteos.uy import silver
from sorteos.uy.parsers import pozos_pdf, resultados
from sorteos.uy.parsers.common import Ball, BlockError, ParsedDraw, Prize
from sorteos.uy.sources import ORO, QN, QV

UY = Path(__file__).parents[2] / "fixtures" / "uy"
RUN = silver.Run(datetime(2026, 10, 28, 12, 0), "run-1")


class Lake:
    """A manifest and a bronze store in tmp_path, filled with fixture pages."""

    def __init__(self, root: Path) -> None:
        self.bronze = BronzeStore(root, "uy")
        self.manifest = mf.SqliteManifest(root / "manifest.sqlite")

    def put(
        self,
        source: str,
        day: date,
        content: bytes,
        state: str = mf.DRAW,
        games: tuple[str, ...] = (),
        extension: str = "html",
    ) -> str:
        key = self.bronze.key(source, day, extension)
        self.bronze.write(key, content)
        record = mf.Record(
            source, day, "u", state, "2026-10-28", games=games, content=content, bronze_key=key
        )
        self.manifest.record(record)
        return key

    def fixture(self, source: str, day: date, state: str = mf.DRAW) -> str:
        content = (UY / f"{source}_{day}.html").read_bytes()
        return self.put(source, day, content, state, _games(source, content, day))

    def pozos(self, day: date, content: bytes, state: str = mf.DRAW) -> str:
        return self.put(pozos_pdf.SOURCE, day, content, state, extension="pdf")

    def year(self, year: int) -> silver.YearRows:
        return silver.build_year(year, self.manifest, self.bronze, RUN)


def _games(source: str, content: bytes, day: date) -> tuple[str, ...]:
    """The games of a results page, as the backfill's classifier stores them."""
    if source != "resultados":
        return ()
    try:
        page = resultados.parse(content, day)
    except resultados.PageError:
        return ()
    return tuple(d.game for d in page.draws) + tuple(f.game for f in page.failed)


@pytest.fixture
def lake(tmp_path):
    lake = Lake(tmp_path)
    yield lake
    lake.manifest.close()


def by_game(rows):
    return {r["game"]: r for r in rows}


# --- whole days from the fixtures ---------------------------------------------------------


def test_a_5_de_oro_with_its_extract(lake):
    day = date(2025, 2, 9)
    key = lake.fixture("resultados", day)
    lake.fixture("extracto_5_de_oro", day)
    rows = lake.year(2025)

    (draw,) = rows.draws
    assert draw["game"] == ORO and draw["draw_date"] == day
    assert draw["cross_source_check"] == silver.MATCH
    assert draw["draw_number"] is None  # no pozos PDF read anywhere in this lake
    assert draw["started_local"] is None  # timing is only the Quiniela's (P2)
    assert draw["timezone"] == "America/Montevideo"
    assert draw["dq_flags"] == []
    assert draw["source_key"] == key
    assert draw["parser_version"] == "resultados:1;extracto_5_de_oro:1"
    assert [(n["ball_type"], n["position"]) for n in rows.draw_numbers][:6] == [
        ("oro", 1),
        ("oro", 2),
        ("oro", 3),
        ("oro", 4),
        ("oro", 5),
        ("extra", 1),
    ]
    assert {n["is_draw_order"] for n in rows.draw_numbers} == {False}  # published sorted
    assert {n["is_replacement"] for n in rows.draw_numbers} == {None}
    assert [p["prize"] for p in rows.prizes] == ["oro", "plata", "revancha"]
    assert {p["currency"] for p in rows.prizes} == {"UYU"}
    assert rows.quarantine == []


def test_the_quiniela_takes_its_timing_from_the_extract_and_a_missing_extract_is_not_checked(lake):
    day = date(2006, 8, 31)
    lake.fixture("resultados", day)
    lake.fixture("extracto_quiniela_vespertina", day)  # the Nocturna's extract is not there
    rows = lake.year(2006)
    draws = by_game(rows.draws)

    vespertina, nocturna = draws[QV], draws[QN]
    assert vespertina["cross_source_check"] == silver.MATCH
    assert vespertina["parser_version"] == "resultados:1;extracto_quiniela_vespertina:1"
    assert vespertina["started_local"] is None  # 2006: the extract publishes it empty
    assert nocturna["cross_source_check"] == silver.NOT_CHECKED
    assert nocturna["parser_version"] == "resultados:1"
    assert nocturna["started_local"] is None

    numbers = [n for n in rows.draw_numbers if n["game"] == QV]
    assert {n["ball_type"] for n in numbers} == {"quiniela"}  # published without its Tómbola
    assert {n["is_draw_order"] for n in numbers} == {True}
    tombola = [n for n in rows.draw_numbers if n["game"] == QN and n["ball_type"] == "tombola"]
    assert len(tombola) == 20 and {n["is_draw_order"] for n in tombola} == {False}
    # this Nocturna's Tómbola repeats a number (one of the 31 of 2006): P7 cannot hold
    assert nocturna["dq_flags"] == [dq.TOMBOLA_REPEATED_NUMBER, dq.TOMBOLA_NOT_FROM_QUINIELA]
    assert {n["is_replacement"] for n in tombola} == {None}
    assert rows.prizes == []


def test_p7_on_a_real_tombola_the_replacements_fill_the_repeated_endings(lake):
    lake.fixture("resultados", date(2016, 7, 6))
    rows = lake.year(2016)
    for game in (QV, QN):
        mine = [n for n in rows.draw_numbers if n["game"] == game]
        endings = {n["number"][-2:] for n in mine if n["ball_type"] == "quiniela"}
        tombola = [n for n in mine if n["ball_type"] == "tombola"]
        replaced = [n["number"] for n in tombola if n["is_replacement"]]
        assert len(tombola) == 20 and None not in {n["is_replacement"] for n in tombola}
        assert len(replaced) == 20 - len(endings)
        assert not set(replaced) & endings
        assert by_game(rows.draws)[game]["dq_flags"] == []


def test_pozo_de_plata_equal_to_oro_is_kept_and_flagged_on_plata(lake):
    lake.fixture("resultados", date(2006, 12, 6))
    prizes = {p["prize"]: p for p in lake.year(2006).prizes}
    assert prizes["plata"]["pool_amount"] == prizes["oro"]["pool_amount"]
    assert prizes["plata"]["dq_flags"] == [dq.POZO_PLATA_EQUALS_ORO]
    assert prizes["oro"]["dq_flags"] == []


def test_an_announcement_that_is_not_a_date_is_flagged(lake):
    lake.fixture("resultados", date(2023, 9, 29))
    nocturna = by_game(lake.year(2023).draws)[QN]
    assert nocturna["next_draw_text"] and nocturna["next_draw_date"] is None
    assert nocturna["dq_flags"] == [dq.NEXT_DRAW_UNPARSED]


def test_only_days_the_manifest_has_as_draw_are_read(lake):
    lake.fixture("resultados", date(2025, 12, 25), mf.NO_DRAW)
    lake.manifest.overrides = {}
    assert lake.year(2025) == silver.YearRows()


# --- quarantine --------------------------------------------------------------------------


def test_a_page_that_does_not_parse_takes_the_whole_day(lake):
    day = date(2019, 9, 25)  # the AFAL strike: a header and no extract link
    key = lake.fixture("resultados", day)
    rows = lake.year(2019)
    assert rows.draws == rows.draw_numbers == rows.prizes == []
    (quarantined,) = rows.quarantine
    assert quarantined["source"] == "resultados" and quarantined["game"] is None
    assert quarantined["source_key"] == key and quarantined["parser_version"] == "resultados:1"
    assert quarantined["reason"] == "1 block headers for 0 extract links"


def test_an_extract_there_but_unreadable_quarantines_only_its_draw(lake):
    day = date(2006, 8, 31)
    lake.fixture("resultados", day)
    lake.put("extracto_quiniela_vespertina", day, b"<html>not an extract</html>")
    rows = lake.year(2006)
    assert [d["game"] for d in rows.draws] == [QN]
    (quarantined,) = rows.quarantine
    assert quarantined["source"] == "extracto_quiniela_vespertina"
    assert quarantined["game"] == QV
    assert quarantined["parser_version"] == "resultados:1;extracto_quiniela_vespertina:1"


def test_a_block_that_does_not_parse_quarantines_only_its_draw(lake, monkeypatch):
    day = date(2025, 2, 9)
    lake.fixture("resultados", day)
    lake.fixture("extracto_5_de_oro", day)
    real = resultados.parse

    def one_block_fails(content, when):
        page = real(content, when)
        failed = resultados.FailedDraw(ORO, when, "the block is broken")
        return dataclasses.replace(page, draws=(), failed=(failed,))

    monkeypatch.setattr(resultados, "parse", one_block_fails)
    rows = lake.year(2025)
    assert rows.draws == []
    assert [(q["game"], q["reason"]) for q in rows.quarantine] == [(ORO, "the block is broken")]


def test_numbers_outside_the_range_of_game_rules_quarantine_the_draw(lake, monkeypatch):
    day = date(2025, 2, 9)
    lake.fixture("resultados", day)
    narrow = {(ORO, "rango_numeros"): [silver.shapes.Range(1, 9, None, None)]}
    monkeypatch.setattr(silver, "RANGES", narrow)
    rows = lake.year(2025)
    assert rows.draws == []
    (quarantined,) = rows.quarantine
    assert quarantined["source"] == "resultados" and quarantined["game"] == ORO
    assert "outside 01-09" in quarantined["reason"]


def test_a_bronze_file_that_is_not_what_was_fetched_stops_the_run(lake):
    day = date(2025, 2, 9)
    key = lake.fixture("resultados", day)
    lake.bronze.write(key, b"changed after the fetch")
    with pytest.raises(silver.BronzeMismatch, match=key):
        lake.year(2025)


# --- the draw number (UY-025.3) -----------------------------------------------------------


@pytest.fixture
def fake_pozos(monkeypatch):
    """A pozos PDF whose bytes are its draw number, or b"broken"."""

    def parse(content, day):
        if content == b"broken":
            raise BlockError("not a readable PDF (PDFSyntaxError)")
        return pozos_pdf.ParsedPozos(day, int(content), datetime(2020, 1, 1, 21, 0), ())

    monkeypatch.setattr(pozos_pdf, "parse", parse)


def oro_days(lake, *days):
    for day in days:  # the series reads the manifest's games, never these bytes
        lake.put("resultados", day, f"page {day}".encode(), games=(ORO,))


def numbers(series):
    return {day: (n.number, n.flags) for day, n in series.items()}


D = [date(2020, 1, 5 + 3 * i) for i in range(6)]
INFERRED = (dq.DRAW_NUMBER_INFERRED,)


def test_the_series_keeps_what_was_published_and_infers_the_rest(lake, fake_pozos):
    oro_days(lake, *D)
    lake.put("resultados", date(2020, 1, 6), b"x", games=(QN,))  # no 5 de Oro: does not count
    lake.pozos(D[0], b"100")
    lake.pozos(D[2], b"102")
    lake.pozos(D[3], b"104")  # 103 was expected
    lake.pozos(D[4], b"", state=mf.ERROR)
    lake.pozos(D[5], b"106")  # counted from 104, the last published
    series = silver.number_series(lake.manifest, lake.bronze)
    assert numbers(series) == {
        D[0]: (100, ()),
        D[1]: (101, INFERRED),  # no PDF linked that day
        D[2]: (102, ()),
        D[3]: (104, (dq.DRAW_NUMBER_OUT_OF_SEQUENCE,)),
        D[4]: (105, INFERRED),  # the PDF is an error
        D[5]: (106, ()),
    }
    assert (series[D[0]].version, series[D[1]].version) == (1, None)


def test_the_first_draws_without_a_pdf_count_back_from_the_next(lake, fake_pozos):
    oro_days(lake, *D[:3])
    lake.pozos(D[2], b"50")
    assert numbers(silver.number_series(lake.manifest, lake.bronze)) == {
        D[0]: (48, INFERRED),
        D[1]: (49, INFERRED),
        D[2]: (50, ()),
    }


def test_the_series_starts_with_the_first_pozos_pdf(lake, fake_pozos):
    oro_days(lake, date(2016, 5, 29), date(2016, 6, 1))
    lake.pozos(date(2016, 6, 1), b"1847")
    assert list(silver.number_series(lake.manifest, lake.bronze)) == [pozos_pdf.FIRST_DAY]


def test_without_any_pdf_read_the_number_stays_null_and_unflagged(lake):
    oro_days(lake, D[0])
    assert numbers(silver.number_series(lake.manifest, lake.bronze)) == {D[0]: (None, ())}
    empty = Lake(lake.bronze.root / "empty")
    assert silver.number_series(empty.manifest, empty.bronze) == {}
    empty.manifest.close()


def test_the_real_first_pozos_pdf_gives_1847(lake):
    day = date(2016, 6, 1)
    oro_days(lake, day)
    lake.pozos(day, (UY / "pozos_5_de_oro_2016-06-01.pdf").read_bytes())
    (number,) = silver.number_series(lake.manifest, lake.bronze).values()
    assert (number.number, number.flags, number.version) == (1847, (), 1)


def test_the_draw_takes_its_number_and_the_pozos_lineage(lake, fake_pozos):
    day = date(2025, 2, 9)
    lake.fixture("resultados", day)
    lake.fixture("extracto_5_de_oro", day)
    lake.pozos(day, b"2780")
    (draw,) = lake.year(2025).draws
    assert (draw["draw_number"], draw["dq_flags"]) == (2780, [])
    assert draw["parser_version"] == "resultados:1;extracto_5_de_oro:1;pozos_5_de_oro:1"


def test_an_inferred_number_is_flagged_and_has_no_pozos_lineage(lake, fake_pozos):
    day = date(2025, 2, 9)
    lake.fixture("resultados", day)
    oro_days(lake, date(2024, 12, 29))  # in another year: the series crosses it
    lake.pozos(date(2024, 12, 29), b"2770")
    (draw,) = lake.year(2025).draws
    assert (draw["draw_number"], draw["dq_flags"]) == (2771, [dq.DRAW_NUMBER_INFERRED])
    assert draw["parser_version"] == "resultados:1"


def test_a_pdf_that_does_not_parse_quarantines_its_draw_and_still_counts(lake, fake_pozos):
    day = date(2025, 2, 9)
    lake.fixture("resultados", day)
    oro_days(lake, date(2024, 12, 29), date(2026, 1, 4))
    lake.pozos(date(2024, 12, 29), b"10")
    key = lake.pozos(day, b"broken")
    lake.pozos(date(2026, 1, 4), b"12")
    series = silver.number_series(lake.manifest, lake.bronze)
    assert series[date(2026, 1, 4)].flags == ()  # 10 + the two draws since, the broken one too

    rows = silver.build_year(2025, lake.manifest, lake.bronze, RUN, series)
    assert rows.draws == []
    (quarantined,) = rows.quarantine
    assert (quarantined["source"], quarantined["game"]) == (pozos_pdf.SOURCE, ORO)
    assert quarantined["source_key"] == key
    assert quarantined["reason"] == "not a readable PDF (PDFSyntaxError)"
    assert quarantined["parser_version"] == "resultados:1;pozos_5_de_oro:1"


def test_a_5_de_oro_the_manifest_does_not_list_stops_the_run(lake):
    day = date(2025, 2, 9)
    lake.put("resultados", day, (UY / f"resultados_{day}.html").read_bytes(), games=(QN,))
    with pytest.raises(silver.SeriesMismatch, match="2025-02-09"):
        lake.year(2025)


def test_a_series_given_is_used_as_it_is(lake):
    day = date(2025, 2, 9)
    lake.fixture("resultados", day)
    rows = silver.build_year(2025, lake.manifest, lake.bronze, RUN, {day: silver.DrawNumber(7)})
    assert rows.draws[0]["draw_number"] == 7


# --- the rules of one draw, on parsed draws ------------------------------------------------


def quiniela(quiniela_numbers, tombola_numbers, **changes):
    balls = [Ball("quiniela", i, n) for i, n in enumerate(quiniela_numbers, start=1)]
    balls += [Ball("tombola", i, n) for i, n in enumerate(tombola_numbers, start=1)]
    draw = ParsedDraw(QN, date(2016, 6, 1), None, None, tuple(balls))
    return dataclasses.replace(draw, **changes)


QUINIELA = [f"{n:03d}" for n in range(100, 120)]  # endings 00..19: no repeated ending
REPEATED_ENDING = [*QUINIELA[:19], "200"]  # 200 ends like 100: one replacement is needed


def test_p7_a_tombola_number_is_a_replacement_when_no_quiniela_number_ends_with_it():
    endings = sorted(n[-2:] for n in REPEATED_ENDING)
    tombola = sorted({*endings, "77"})
    replacements, flags = silver._replacements(
        quiniela(REPEATED_ENDING, tombola), silver.CONFIG.games[QN].numbers
    )
    assert flags == []
    assert [p for p, is_new in replacements["tombola"].items() if is_new] == [
        tombola.index("77") + 1
    ]


@pytest.mark.parametrize(
    ("tombola", "flags"),
    [
        # a repeated number: the endings cannot all fit, so P7 fails too (the 31 of 2006)
        (sorted([f"{n:02d}" for n in range(19)] + ["18"]), ["repeated", "not_from"]),
        # an ending missing
        (sorted([f"{n:02d}" for n in range(1, 20)] + ["77"]), ["not_from"]),
        # more replacements than repeated endings
        (sorted([f"{n:02d}" for n in range(19)] + ["77"]), ["not_from"]),
    ],
)
def test_p7_when_it_does_not_hold_is_replacement_stays_null(tombola, flags):
    names = {"repeated": dq.TOMBOLA_REPEATED_NUMBER, "not_from": dq.TOMBOLA_NOT_FROM_QUINIELA}
    replacements, found = silver._replacements(
        quiniela(QUINIELA, tombola), silver.CONFIG.games[QN].numbers
    )
    assert found == [names[f] for f in flags]
    assert replacements == {}


def test_the_timing_is_the_extracts_and_only_the_quinielas():
    at = datetime(2016, 6, 1, 21, 0)
    rows = silver.YearRows()
    page = silver._Page("resultados", "k", "0" * 64, b"")
    timing = quiniela(QUINIELA, [], started_local=at, ended_local=at)
    silver._rows(quiniela(QUINIELA, []), timing, page, {"resultados": 1}, RUN, rows)
    silver._rows(
        five_de_oro(),
        dataclasses.replace(five_de_oro(), started_local=at),
        page,
        {"resultados": 1},
        RUN,
        rows,
    )
    draws = by_game(rows.draws)
    assert (draws[QN]["started_local"], draws[QN]["ended_local"]) == (at, at)
    assert draws[ORO]["started_local"] is None


@pytest.mark.parametrize(
    ("started", "first", "ended", "flagged"),
    [
        ((21, 0), (21, 2), (21, 20), False),
        ((21, 0), None, (15, 24), True),  # Nocturna 2009-08-01
        (None, None, None, False),  # 2006: published empty
        ((21, 0), (21, 0), (21, 0), False),
    ],
)
def test_timing_out_of_order(started, first, ended, flagged):
    def at(hm):
        return datetime(2016, 6, 1, *hm) if hm else None

    timing = quiniela(QUINIELA, [], started_local=at(started), ended_local=at(ended))
    timing = dataclasses.replace(timing, first_ball_local=at(first))
    assert (dq.TIMING_OUT_OF_ORDER in silver._draw_flags(timing, timing)) is flagged


@pytest.mark.parametrize(
    ("announced", "flagged"),
    [
        (date(2016, 6, 2), False),
        (date(2016, 6, 15), False),
        (date(2016, 6, 16), True),
        (date(2016, 6, 1), True),
        (date(2016, 5, 31), True),
    ],
)
def test_an_announcement_beyond_14_days_or_not_after_the_draw_is_implausible(announced, flagged):
    draw = quiniela(QUINIELA, [], next_draw_text="x", next_draw_date=announced)
    assert (dq.NEXT_DRAW_IMPLAUSIBLE in silver._draw_flags(draw, None)) is flagged


def five_de_oro(pool=Decimal("100.00"), extra="05"):
    sorted_five = ("01", "02", "03", "04", "06")
    balls = (
        *(Ball("oro", i, n) for i, n in enumerate(sorted_five, start=1)),
        Ball("extra", 1, extra),
        *(Ball("revancha", i, n) for i, n in enumerate(sorted_five, start=1)),
    )
    prizes = tuple(Prize(name, pool, "no_winners", 0) for name in ("oro", "plata", "revancha"))
    return ParsedDraw(ORO, date(2016, 6, 1), None, None, balls, prizes)


@pytest.mark.parametrize(
    ("other", "check", "flagged_prizes"),
    [
        (five_de_oro(), silver.MATCH, []),
        (five_de_oro(pool=Decimal("100.01")), silver.MATCH, ["oro", "plata", "revancha"]),
        (five_de_oro(extra="07"), silver.MISMATCH, []),
    ],
)
def test_an_amount_difference_is_a_prize_flag_and_any_other_difference_a_mismatch(
    other, check, flagged_prizes
):
    rows = silver.YearRows()
    page = silver._Page("resultados", "k", "0" * 64, b"")
    silver._rows(five_de_oro(), other, page, {"resultados": 1}, RUN, rows)
    assert rows.draws[0]["cross_source_check"] == check
    differ = [p["prize"] for p in rows.prizes if dq.AMOUNT_SOURCES_DIFFER in p["dq_flags"]]
    assert differ == flagged_prizes


# --- writing -----------------------------------------------------------------------------


def test_a_year_and_the_reference_tables_are_written_with_the_catalog(lake, tmp_path):
    day = date(2006, 8, 31)
    lake.fixture("resultados", day)
    lake.fixture("extracto_quiniela_vespertina", day)
    lake.fixture("resultados", date(2006, 12, 6))
    out = tmp_path / "silver"
    written = silver.write_year(out, 2006, lake.year(2006))
    names = sorted(p.relative_to(out).as_posix() for p in written)
    assert names == [
        "draw_numbers/country=uy/game=5_de_oro/year=2006/part-0.parquet",
        "draw_numbers/country=uy/game=quiniela_nocturna/year=2006/part-0.parquet",
        "draw_numbers/country=uy/game=quiniela_vespertina/year=2006/part-0.parquet",
        "draws/country=uy/game=5_de_oro/year=2006/part-0.parquet",
        "draws/country=uy/game=quiniela_nocturna/year=2006/part-0.parquet",
        "draws/country=uy/game=quiniela_vespertina/year=2006/part-0.parquet",
        "prizes/country=uy/game=5_de_oro/year=2006/part-0.parquet",
    ]
    nocturna = pq.read_table(out / "draws/country=uy/game=quiniela_nocturna/year=2006")
    assert nocturna.num_rows == 2  # 2006-08-31 and 2006-12-06

    reference = silver.write_reference(out, RUN)
    assert [p.relative_to(out).parts[0] for p in reference] == ["game_rules", "calendar_events"]
    assert pq.read_table(reference[1]).num_rows == 59
