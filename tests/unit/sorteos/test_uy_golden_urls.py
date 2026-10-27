"""The golden URLs (UY-020): what the manifest requested, rebuilt from the YAML.

`make uy-golden-urls` checks all ~20,600 rows of the local manifest. CI has no manifest, so
it checks the fixed sample in tests/fixtures/uy/golden_urls.json, taken from it.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

from sorteos.core import bronze

REPO = Path(__file__).parents[3]
SAMPLE = json.loads((REPO / "tests" / "fixtures" / "uy" / "golden_urls.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def golden():
    spec = importlib.util.spec_from_file_location(
        "uy_golden_urls", REPO / "scripts" / "uy_golden_urls.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows(sample=SAMPLE):
    return [(r["source"], r["draw_date"], r["url"]) for r in sample]


def test_every_sampled_url_comes_out_of_the_yaml_unchanged(golden):
    checked, skipped, mismatches = golden.compare(rows())
    assert mismatches == []
    assert (checked, skipped) == (len(SAMPLE), 0)


def test_the_sample_covers_every_source_and_every_shape():
    by_source: dict[str, list[date]] = {}
    for r in SAMPLE:
        by_source.setdefault(r["source"], []).append(date.fromisoformat(r["draw_date"]))
    assert len(by_source) == 7  # every source a date rebuilds; pozos comes from a link
    for name, days in by_source.items():
        mixes = {(d.day < 10, d.month < 10) for d in days}
        assert mixes == {(True, True), (True, False), (False, True), (False, False)}, name
        if not name.startswith("extracto_pdf_"):
            assert min(days) < date(2018, 11, 30) <= max(days), name


@pytest.mark.parametrize(
    ("row", "problem"),
    [
        (
            (
                "resultados",
                "2016-07-06",
                "https://www.loteria.gub.uy/ver_resultados.php?vdia=06&vmes=07&vano=2016",
            ),
            "!= yaml",
        ),
        (
            (
                "extracto_pdf_5_de_oro",
                "2018-11-29",
                "https://www.loteria.gub.uy/extractosweb/20181129o.pdf",
            ),
            "before the source's valid_from",
        ),
        (("extracto_kini", "2010-01-04", "https://www.loteria.gub.uy/x"), "no such source"),
    ],
)
def test_a_difference_is_reported_not_swallowed(golden, row, problem):
    checked, skipped, mismatches = golden.compare([row])
    assert len(mismatches) == 1 and problem in mismatches[0]


def test_the_pozos_pdf_is_skipped_because_its_url_is_a_link(golden):
    row = ("pozos_5_de_oro", "2016-07-06", "https://www.loteria.gub.uy/invalidas/06072016/x.PDF")
    assert golden.compare([row]) == (0, 1, [])


def _manifest(tmp_path, extra=()):
    path = tmp_path / "manifest.sqlite"
    manifest = bronze.Manifest(path)
    for source, day, url in [*rows(SAMPLE[:3]), *extra]:
        manifest.record(
            bronze.Record(source, date.fromisoformat(day), url, "draw", "2026-10-26T00:00:00+00:00")
        )
    manifest.close()
    return path


def test_main_reads_a_manifest_and_writes_a_sample(golden, tmp_path, capsys):
    out = tmp_path / "sample.json"
    assert golden.main([str(_manifest(tmp_path)), "--write-sample", str(out)]) == 0
    assert "3 URLs rebuilt from the YAML, 0 differ, 0 skipped" in capsys.readouterr().out
    assert [r["source"] for r in json.loads(out.read_text("utf-8"))] == [
        r[0] for r in rows(SAMPLE[:3])
    ]


def test_main_fails_when_one_url_differs(golden, tmp_path, capsys):
    wrong = (
        "resultados",
        "2016-07-06",
        "https://www.loteria.gub.uy/ver_resultados.php?vdia=6&vmes=7&vano=16",
    )
    assert golden.main([str(_manifest(tmp_path, [wrong]))]) == 1
    captured = capsys.readouterr()
    assert "1 differ" in captured.out and "resultados 2016-07-06" in captured.err
