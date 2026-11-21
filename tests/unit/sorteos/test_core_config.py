"""The strict YAML loader (UY-020; docs/uruguay/DESIGN.md, D4 and P4).

Every broken case is the real Uruguayan configuration with one edit, so each test says what
one mistake looks like and that the loader names it.
"""

from __future__ import annotations

import shutil
from datetime import date, time
from pathlib import Path

import pytest

import sorteos.uy
from sorteos.core import config
from sorteos.core.config import ConfigError, load_country
from sorteos.uy import sources

UY_DIR = Path(sorteos.uy.__file__).parent


@pytest.fixture(scope="module")
def uy():
    return load_country(UY_DIR)


def broken(tmp_path: Path, relative: str, old: str, new: str) -> Path:
    """A copy of the Uruguayan configuration with ``old`` replaced by ``new`` in one file."""
    root = tmp_path / "uy"
    root.mkdir()
    shutil.copy(UY_DIR / "site.yaml", root / "site.yaml")
    shutil.copytree(UY_DIR / "games", root / "games")
    shutil.copytree(UY_DIR / "reference", root / "reference")
    target = root / relative
    text = target.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{old!r} must appear exactly once in {relative}"
    target.write_text(text.replace(old, new), encoding="utf-8")
    return root


def fails(tmp_path, relative, old, new, match):
    with pytest.raises(ConfigError, match=match):
        load_country(broken(tmp_path, relative, old, new))


# --- The real configuration -------------------------------------------------------------------


def test_the_uruguayan_configuration_loads(uy):
    assert uy.site.country == "uy" and uy.site.operator == "dnlq" and uy.site.currency == "UYU"
    assert uy.site.history_starts == date(2006, 8, 11)
    assert sorted(uy.games) == ["5_de_oro", "quiniela_nocturna", "quiniela_vespertina"]
    assert uy.games["quiniela_nocturna"].calendar.publish_after_local == time(21, 30)
    assert uy.games["quiniela_vespertina"].calendar.weekdays == ("mon", "tue", "wed", "thu", "fri")
    assert uy.games["5_de_oro"].numbers["extra"].not_in == ("oro",)
    assert ("5_de_oro", "rango_numeros") in uy.rules


# What the hand-written _FIXED_CODES of UY-001 did, spelled out: the YAML must keep it.
_CODES_BEFORE_UY_020 = {2: "kini", 3: "quiniela_vespertina", 4: "quiniela_nocturna"}
_CODES_BEFORE_UY_020 |= {5: "5_de_oro", 19: "quiniela_vn", 1: "loteria"}
_CODES_BEFORE_UY_020 |= {c: "loteria" for c in range(6, 27) if c != 19}
# UY-022: the Lotería codes of the draws since 2018-12 (mapped in UY-006). Unknown until then,
# they sent 15 days to quarantine whole once ver_resultados was parsed.
_CODES_BEFORE_UY_020 |= {c: "loteria" for c in range(27, 39)}


@pytest.mark.parametrize("code", range(0, 60))
def test_every_site_code_routes_where_it_did_before_the_yaml(code):
    assert sources.game_for_code(code) == _CODES_BEFORE_UY_020.get(code, f"unknown_{code}")


def test_the_source_names_are_the_manifest_keys_and_keep_their_order():
    # Renaming one would orphan its manifest rows; reordering would change the fetch order.
    assert list(sources.ALL_SOURCES) == [
        "resultados",
        "extracto_5_de_oro",
        "extracto_quiniela_vespertina",
        "extracto_quiniela_nocturna",
        "extracto_pdf_5_de_oro",
        "extracto_pdf_quiniela_vespertina",
        "extracto_pdf_quiniela_nocturna",
        "pozos_5_de_oro",
    ]
    assert [s.extension for s in sources.ALL_SOURCES.values()] == ["html"] * 4 + ["pdf"] * 4
    assert sources.COUNTRY == "uy" and sources.BASE_URL == "https://www.loteria.gub.uy"


def test_the_pdf_extracts_start_the_day_the_site_switched_to_them():
    for source in sources.EXTRACTOS_PDF:
        assert not source.applies_to(date(2018, 11, 29))
        assert source.applies_to(date(2018, 11, 30))
    assert all(s.applies_to(date(2006, 8, 1)) for s in sources.EXTRACTOS_PHP)


def test_the_guard_is_not_configuration():
    # P5: a YAML must never be able to touch the privacy blocklist.
    for path in UY_DIR.rglob("*.yaml"):
        text = path.read_text(encoding="utf-8").upper()
        assert "DET_INVALIDAS" not in text and "BLOCKLIST" not in text, path.name


# --- What the loader refuses ----------------------------------------------------------------


def test_an_unknown_key_is_named(tmp_path):
    fails(
        tmp_path,
        "site.yaml",
        'currency: "UYU"',
        'currency: "UYU"\ncurency: "UYU"',
        r"\['curency'\]",
    )


def test_a_missing_key_is_named(tmp_path):
    fails(tmp_path, "site.yaml", 'currency: "UYU"\n', "", "missing 'currency'")


def test_a_duplicate_key_is_an_error_not_the_last_one_wins(tmp_path):
    fails(
        tmp_path,
        "site.yaml",
        'currency: "UYU"',
        'currency: "UYU"\ncurrency: "USD"',
        "duplicate key 'currency'",
    )


def test_an_unquoted_no_never_becomes_false(tmp_path):
    fails(
        tmp_path,
        "site.yaml",
        'operator_name: "Dirección Nacional de Loterías y Quinielas"',
        "operator_name: no",
        "quoted string, got bool",
    )


def test_an_unquoted_date_never_becomes_a_date_object(tmp_path):
    fails(
        tmp_path,
        "site.yaml",
        'history_starts: "2006-08-11"',
        "history_starts: 2006-08-11",
        "quoted string, got date",
    )


def test_a_boolean_is_not_a_count(tmp_path):
    fails(
        tmp_path,
        "games/5_de_oro.yaml",
        "extra: {count: 1,",
        "extra: {count: yes,",
        "expected an integer",
    )


@pytest.mark.parametrize(
    ("relative", "old", "new", "match"),
    [
        ("site.yaml", 'country: "uy"', 'country: "UY"', r"does not match \[a-z\]\{2\}"),
        (
            "site.yaml",
            'timezone: "America/Montevideo"',
            'timezone: "America/Montevide"',
            "unknown time zone",
        ),
        ("site.yaml", 'history_starts: "2006-08-11"', 'history_starts: "2006-02-30"', "not a date"),
        (
            "site.yaml",
            'base_url: "https://www.loteria.gub.uy"',
            'base_url: "http://www.loteria.gub.uy"',
            "base_url",
        ),
        ("site.yaml", 'vdia: "{day}"', 'vdia: "{dia}"', r"unknown placeholder\(s\) \['dia'\]"),
        ("site.yaml", 'vdia: "{day}"', 'vdia: "{day"', "not a usable template"),
        ("site.yaml", 'money_style: "us"', 'money_style: "eu"', "is not one of"),
        ("site.yaml", "pages:\n  resultados:", "pages:\n  1:", "quoted string, got int 1"),
        ("site.yaml", 'vdia: "{day}"', '1: "{day}"', "keys must be text, got 1"),
        ("site.yaml", 'operator: "dnlq"', 'operator: "   "', "operator: empty"),
        ("site.yaml", "loteria: [1,", 'loteria: ["1",', "neither a code nor"),
        ("site.yaml", '"6-18"', '"18-6"', "empty range"),
        ("site.yaml", "quiniela_vn: [19]", "quiniela_vn: [19, 19]", "listed twice"),
        ("site.yaml", "quiniela_vn: [19]", "quiniela_vn: 19", "non-empty list of codes"),
        (
            "site.yaml",
            '  - {version: 1, valid_from: "2006-08-11"}',
            '  - {version: 1, valid_from: "2006-08-11", valid_to: "2006-01-01"}',
            "valid_to is before",
        ),
        (
            "site.yaml",
            "parser_epochs:\n      - {version: 1,",
            "parser_epochs: {}\n      # - {version: 1,",
            "non-empty list",
        ),
    ],
)
def test_the_site_file_is_checked_field_by_field(tmp_path, relative, old, new, match):
    fails(tmp_path, relative, old, new, match)


@pytest.mark.parametrize(
    ("old", "new", "match"),
    [
        ('game: "5_de_oro"', 'game: "cinco_de_oro"', "does not match the file name"),
        ('weekdays: ["wed", "sun"]', 'weekdays: ["wed", "dom"]', "is not one of"),
        ('weekdays: ["wed", "sun"]', 'weekdays: ["wed", "wed"]', "repeated values"),
        ('weekdays: ["wed", "sun"]', "weekdays: []", "non-empty list"),
        ('publish_after_local: "22:30"', 'publish_after_local: "24:30"', "does not match"),
        (
            'range_rule: "rango_numeros"}\n  extra',
            'range_rule: "rango"}\n  extra',
            "not in game_rules.csv",
        ),
        ('not_in: ["oro"]', 'not_in: ["plata"]', "'plata' is not another ball type"),
        ('not_in: ["oro"]', 'not_in: ["extra"]', "'extra' is not another ball type"),
        (
            'order: "sorted", repeats: false, range_rule: "rango_numeros"}\n  extra',
            'order: "random", repeats: false, range_rule: "rango_numeros"}\n  extra',
            "is not one of",
        ),
        (
            'repeats: false, range_rule: "rango_numeros"}\n  extra',
            'repeats: "no", range_rule: "rango_numeros"}\n  extra',
            "true or false",
        ),
        (
            '{name: "resultados", role: "primary"}',
            '{name: "resultado", role: "primary"}',
            "not a page of site.yaml",
        ),
        (
            '{name: "resultados", role: "primary"}',
            '{name: "resultados", role: "main"}',
            "is not one of",
        ),
        (
            'kind: "pozos_pdf"\n',
            'kind: "pozos_pdf"\n    path: "/x.pdf"\n',
            "no path",
        ),
        (
            '    valid_from: "2018-11-30"',
            '    valid_from: "2018-11-30"\n'
            '    parser_epochs: [{version: 1, valid_from: "2018-11-30"}]',
            "never parsed",
        ),
        ('    valid_from: "2018-11-30"', "", "missing 'valid_from'"),
        (
            '    parser_epochs: [{version: 1, valid_from: "2006-08-11"}]\n'
            '  - name: "extracto_pdf_5_de_oro"',
            '  - name: "extracto_pdf_5_de_oro"',
            "missing 'parser_epochs'",
        ),
        (
            '- name: "pozos_5_de_oro"',
            '- name: "extracto_5_de_oro"',
            "source name is repeated",
        ),
        ("prizes:", "prices:", r"unknown key\(s\) \['prices'\]"),
        ("site_code: 5 ", "site_code: 0 ", "must be >= 1"),
        (
            'params: {vdia: "{day:02d}", vmes: "{month:02d}", vano: "{year}"}',
            "params: {}",
            "params: expected a non-empty mapping",
        ),
    ],
)
def test_a_game_file_is_checked_field_by_field(tmp_path, old, new, match):
    fails(tmp_path, "games/5_de_oro.yaml", old, new, match)


def test_parser_epochs_may_follow_each_other_exactly(tmp_path):
    root = broken(
        tmp_path,
        "site.yaml",
        '      - {version: 1, valid_from: "2006-08-11"}',
        '      - {version: 1, valid_from: "2006-08-11", valid_to: "2016-05-28"}\n'
        '      - {version: 2, valid_from: "2016-05-29"}',
    )
    epochs = load_country(root).site.pages["resultados"].parser_epochs
    assert [(e.version, e.valid_from, e.valid_to) for e in epochs] == [
        (1, date(2006, 8, 11), date(2016, 5, 28)),
        (2, date(2016, 5, 29), None),
    ]


@pytest.mark.parametrize(
    ("second", "match"),
    [
        ('{version: 2, valid_from: "2016-05-30"}', "neither overlap nor leave a gap"),  # gap
        ('{version: 2, valid_from: "2016-05-28"}', "neither overlap nor leave a gap"),  # overlap
        ('{version: 1, valid_from: "2016-05-29"}', "must go forward"),
        ('{version: 2, valid_from: "2006-08-11"}', "must go forward"),
    ],
)
def test_parser_epochs_may_not_overlap_nor_leave_a_gap(tmp_path, second, match):
    fails(
        tmp_path,
        "site.yaml",
        '      - {version: 1, valid_from: "2006-08-11"}',
        '      - {version: 1, valid_from: "2006-08-11", valid_to: "2016-05-28"}\n'
        f"      - {second}",
        match,
    )


def test_a_site_code_cannot_belong_to_two_games(tmp_path):
    # The trap the Lotería range sets: "6-26" would swallow Quiniela V+N's 19.
    fails(
        tmp_path, "site.yaml", '[1, "6-18", "20-38"]', '[1, "6-26"]', "site code 19 belongs to both"
    )


def test_a_game_cannot_be_both_a_file_and_an_other_game(tmp_path):
    fails(tmp_path, "site.yaml", "kini: [2]", "kini: [2]\n  5_de_oro: [55]", "both a game file and")


def test_a_source_cannot_be_declared_by_two_games(tmp_path):
    fails(
        tmp_path,
        "games/quiniela_nocturna.yaml",
        '- name: "extracto_pdf_quiniela_nocturna"',
        '- name: "extracto_pdf_quiniela_vespertina"',
        "declared by",
    )


def test_a_country_needs_at_least_one_game(tmp_path):
    root = broken(tmp_path, "site.yaml", 'currency: "UYU"', 'currency: "UYU"')
    for path in (root / "games").glob("*.yaml"):
        path.unlink()
    with pytest.raises(ConfigError, match="no games"):
        load_country(root)


def test_a_file_that_is_not_yaml_or_not_a_mapping_is_named(tmp_path):
    fails(
        tmp_path, "games/5_de_oro.yaml", "prizes:", "prizes: [\n", "5_de_oro.yaml: not valid YAML"
    )
    root = tmp_path / "list"
    root.mkdir()
    (root / "x.yaml").write_text("- a\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="expected a mapping, got list"):
        config.load_site(root / "x.yaml")


def test_game_rules_needs_its_two_key_columns(tmp_path):
    path = tmp_path / "game_rules.csv"
    path.write_text("juego,regla\n5_de_oro,rango_numeros\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="needs 'game' and 'rule'"):
        config.load_rules(path)
