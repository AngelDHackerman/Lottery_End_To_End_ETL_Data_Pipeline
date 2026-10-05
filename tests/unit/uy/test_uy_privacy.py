"""Privacy guard rails that are not about the client itself.

The DNLQ's ``*_DET_INVALIDAS_*`` PDFs carry national ID numbers (Uruguay, Ley 18.331).
Nothing from them may reach this repository — not as a fixture, not as a copied value.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).parents[3]
UY_FIXTURES = REPO / "tests" / "fixtures" / "uy"
FORBIDDEN = ("DET_INVALIDAS", "CÉDULA", "CEDULA")


def _fixture_files():
    # README.md documents the rule, so it names the pattern; everything else is a capture.
    return sorted(p for p in UY_FIXTURES.rglob("*") if p.is_file() and p.name != "README.md")


def test_there_are_fixtures_to_scan():
    assert len(_fixture_files()) >= 8


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_no_fixture_names_the_privacy_files_or_ids(path):
    text = path.read_bytes().decode("utf-8", errors="replace").upper()
    for word in FORBIDDEN:
        assert word not in text, f"{path.name} contains {word!r}"


def _redactor():
    spec = importlib.util.spec_from_file_location(
        "uy_redact_fixture", REPO / "scripts" / "uy_redact_fixture.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_redaction_script_replaces_only_the_privacy_hrefs(tmp_path):
    redactor = _redactor()
    html = (
        '<a href="invalidas/1/Q_DET_INVALIDAS_X.PDF">q</a>'
        "<a href='invalidas/1/t_det_invalidas_y.pdf'>t</a>"
        '<a href="invalidas/1/ORO_RES_INFORMACION_DE_POZOS.PDF">p</a>'
    )
    out, count = redactor.redact(html)
    assert count == 2
    assert "DET_INVALIDAS" not in out.upper()
    assert "RES_INFORMACION_DE_POZOS" in out

    src, dst = tmp_path / "in.html", tmp_path / "out.html"
    src.write_text(html, encoding="utf-8")
    assert redactor.main([str(src), str(dst)]) == 0
    assert "DET_INVALIDAS" not in dst.read_text(encoding="utf-8").upper()

    src.write_text("<p>DET_INVALIDAS in text</p>", encoding="utf-8")
    with pytest.raises(SystemExit):
        redactor.main([str(src), str(dst)])
