"""Privacy guard rails that are not about the client itself.

The DNLQ's ``*_DET_INVALIDAS_*`` PDFs carry national ID numbers (Uruguay, Ley 18.331).
Nothing from them may reach this repository — not as a fixture, not as a copied value.

Winning coupon numbers are not personal data, but the owner kept them in bronze only (C7),
so a committed fixture carries fakes of the same shape instead (UY-011.1).
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


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_no_fixture_carries_a_real_coupon_number(path):
    redactor = _redactor()
    text = path.read_bytes().decode("utf-8", errors="replace")
    for pattern in redactor.COUPON_PATTERNS:
        for coupon in pattern.findall(text):
            assert coupon.startswith(redactor.FAKE_PREFIX), f"{path.name} carries a real coupon"


def test_the_fixtures_still_hold_the_fake_coupons_the_parser_will_count():
    # The scanner above passes trivially if the coupons vanish, so pin that they are there.
    text = (UY_FIXTURES / "resultados_2016-07-06.html").read_text(encoding="utf-8")
    assert [c for p in _redactor().COUPON_PATTERNS for c in p.findall(text)] == [
        "000000001-0",
        "000000002-0",
        "000000003-0",
    ]


# Synthetic numbers, one per shape seen in bronze (2006–2026): never real coupons.
_SHAPES = {
    "12345678-9": "00000001-0",
    "123456789-1": "000000001-0",
    "12345678-9-1": "00000001-0-0",
    "1234567890-1-2": "0000000001-0-0",
    "12345678901-2": "00000000001-0",
}


@pytest.mark.parametrize(("real", "fake"), _SHAPES.items())
def test_the_redaction_script_replaces_every_coupon_shape(real, fake):
    out, count = _redactor().redact_coupons(f"<td> {real} <img alt='separador'></td>")
    assert (out, count) == (f"<td> {fake} <img alt='separador'></td>", 1)


def test_the_redaction_script_numbers_coupons_per_page_and_keeps_everything_else():
    redactor = _redactor()
    html = (
        "<p>Fecha 06/07/2016 sorteo 1857</p>"
        "<td>$ 110,629,426.70</td><td>12.022.391,73</td>"
        '<img alt="gif_trasparente" />\n    123456789-1    <img alt="separador" />'
        "    987654321-0    </td>"
        '<img alt="separador" width="20" height="5">\n     1234567890     </td>'
        '<a href="https://example.test/?id=1234567890">x</a>'
    )
    out, count = redactor.redact_coupons(html)
    assert count == 3
    assert "000000001-0" in out and "000000002-0" in out and "0000000003" in out
    assert (
        out.replace("000000001-0", "123456789-1")
        .replace("000000002-0", "987654321-0")
        .replace("0000000003", "1234567890", 1)
        == html
    )
    assert "id=1234567890" in out  # a bare run outside a cell is not a coupon
    assert redactor.redact_coupons(out) == (out, 3)  # idempotent


def test_the_redaction_script_reports_the_coupons_it_replaced(tmp_path, capsys):
    src, dst = tmp_path / "in.html", tmp_path / "out.html"
    src.write_text("<td> 123456789-1 </td>", encoding="utf-8")
    assert _redactor().main([str(src), str(dst)]) == 0
    assert dst.read_text(encoding="utf-8") == "<td> 000000001-0 </td>"
    assert "1 coupon(s) replaced" in capsys.readouterr().out
