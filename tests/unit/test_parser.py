"""Unit tests for ``loteria.parser.parser`` (PR-029).

The parser is the highest-risk code in the pipeline and the least defended: it turns a
scraped text page into every downstream number, and its inputs change without warning when
loteria.org.gt edits its markup. Everything here runs against **real captured sorteos**
(anonymized — see ``tests/fixtures/sorteos/README.md``) rather than hand-written strings, so
the assertions describe the format the site actually produces.

Expected values are hard-coded from the fixtures on purpose. Deriving them from the parser
would make the tests tautological — they would pass for any parser, including a broken one.
"""

from __future__ import annotations

import pandas as pd
import pytest

from loteria.parser.parser import (
    process_body,
    process_header,
    split_header_body,
    split_vendido_por_column,
)

# Ground truth, read out of the fixtures by hand. If a fixture is regenerated and these stop
# matching, that is the test doing its job — confirm the source data really changed before
# editing the numbers.
EXPECTED = {
    "ordinario_3046": {
        "numero_sorteo": 3046,
        "tipo_sorteo": "ORDINARIO",
        "fecha_sorteo": "01/06/2024",
        "fecha_caducidad": "02/12/2024",
        "primer_premio": 46063,
        "segundo_premio": 40361,
        "tercer_premio": 39987,
        "reintegros": "3,1,7",
        "premios": 875,
        "no_vendido": 19,
    },
    "ordinario_3132": {
        "numero_sorteo": 3132,
        "tipo_sorteo": "ORDINARIO",
        "fecha_sorteo": "08/08/2026",
        "fecha_caducidad": "08/02/2027",
        "primer_premio": 57697,
        "segundo_premio": 74943,
        "tercer_premio": 14958,
        "reintegros": "7,3,8",
        "premios": 895,
        "no_vendido": 10,
    },
    "extraordinario_413": {
        "numero_sorteo": 413,
        "tipo_sorteo": "EXTRAORDINARIO",
        "fecha_sorteo": "19/07/2026",
        "fecha_caducidad": "18/01/2027",
        "primer_premio": 9542,
        "segundo_premio": 19474,
        "tercer_premio": 42267,
        "reintegros": "2,4,7",
        "premios": 1984,
        # An extraordinario in this capture sold every prize. Asserting the zero keeps the
        # suite honest about the fact that "no NO VENDIDO lines" is a real, valid input.
        "no_vendido": 0,
    },
}


# ==========================================================================================
# split_header_body
# ==========================================================================================
class TestSplitHeaderBody:
    @pytest.mark.parametrize("name", list(EXPECTED))
    def test_finds_both_sections_in_every_fixture(self, sorteo_files, name):
        lines = sorteo_files[name].read_text(encoding="utf-8").splitlines()
        header, body = split_header_body(lines)

        assert header, "HEADER section came back empty"
        assert body, "BODY section came back empty"
        # The markers themselves are consumed, not returned.
        assert "HEADER" not in header
        assert "BODY" not in header
        assert "BODY" not in body

    def test_header_stops_where_body_starts(self, ordinario_lines):
        header, body = split_header_body(ordinario_lines)

        assert header[0].startswith("LISTA DEL SORTEO")
        # The first BODY line of a real sorteo is a section label, not a prize row.
        assert body[0] == "CENTENARES"

    def test_blank_lines_are_dropped(self, ordinario_lines):
        header, body = split_header_body(ordinario_lines)
        assert all(line.strip() for line in header + body)

    @pytest.mark.parametrize(
        "lines",
        [
            pytest.param([], id="empty"),
            pytest.param(["HEADER", "NO. 1"], id="header-without-body"),
            pytest.param(["BODY", "00001 P .... 1.00"], id="body-without-header"),
            pytest.param(["some", "unrelated", "text"], id="neither-marker"),
        ],
    )
    def test_raises_valueerror_on_malformed_input(self, lines):
        with pytest.raises(ValueError, match="HEADER or BODY"):
            split_header_body(lines)


# ==========================================================================================
# process_header
# ==========================================================================================
class TestProcessHeader:
    @pytest.mark.parametrize("name", list(EXPECTED))
    def test_extracts_every_field(self, sorteo_files, name):
        lines = sorteo_files[name].read_text(encoding="utf-8").splitlines()
        header, _ = split_header_body(lines)
        result = process_header(header)

        expected = EXPECTED[name]
        for field in (
            "numero_sorteo",
            "tipo_sorteo",
            "fecha_sorteo",
            "fecha_caducidad",
            "primer_premio",
            "segundo_premio",
            "tercer_premio",
            "reintegros",
        ):
            assert result[field] == expected[field], f"{name}: {field}"

    @pytest.mark.parametrize("name", list(EXPECTED))
    def test_types_are_correct(self, sorteo_files, name):
        lines = sorteo_files[name].read_text(encoding="utf-8").splitlines()
        header, _ = split_header_body(lines)
        result = process_header(header)

        # The four ints matter downstream: numero_sorteo is a partition key and the three
        # premios are joined against in the gold layer. A str would poison both.
        assert isinstance(result["numero_sorteo"], int)
        assert isinstance(result["primer_premio"], int)
        assert isinstance(result["segundo_premio"], int)
        assert isinstance(result["tercer_premio"], int)
        assert isinstance(result["fecha_sorteo"], str)
        assert isinstance(result["reintegros"], str)

    def test_reintegros_whitespace_is_stripped(self, ordinario_lines):
        # The raw line is "REINTEGROS 3,1 ,7" — irregular spacing that must not survive.
        header, _ = split_header_body(ordinario_lines)
        assert " " not in process_header(header)["reintegros"]

    def test_distinguishes_ordinario_from_extraordinario(self, sorteo_files):
        for name, expected_tipo in [
            ("ordinario_3046", "ORDINARIO"),
            ("extraordinario_413", "EXTRAORDINARIO"),
        ]:
            lines = sorteo_files[name].read_text(encoding="utf-8").splitlines()
            header, _ = split_header_body(lines)
            assert process_header(header)["tipo_sorteo"] == expected_tipo

    @pytest.mark.parametrize(
        "header",
        [
            pytest.param(["LISTA DEL SORTEO ORDINARIO NO. 3046"], id="only-title"),
            pytest.param(
                [
                    "LISTA DEL SORTEO ORDINARIO NO. 3046",
                    "|PRIMER PREMIO 1 ||| SEGUNDO PREMIO 2 ||| TERCER PREMIO 3|",
                    "REINTEGROS 1,2,3",
                    # fecha lines missing
                ],
                id="missing-fechas",
            ),
            pytest.param(
                [
                    "LISTA DEL SORTEO ORDINARIO NO. 3046",
                    "FECHA DEL SORTEO: 01/06/2024 --- FECHA DE CADUCIDAD: 02/12/2024",
                    "REINTEGROS 1,2,3",
                    # premios line missing
                ],
                id="missing-premios",
            ),
        ],
    )
    def test_raises_valueerror_on_missing_fields(self, header):
        with pytest.raises(ValueError, match="expected format"):
            process_header(header)


# ==========================================================================================
# process_body
# ==========================================================================================
class TestProcessBody:
    @pytest.mark.parametrize("name", list(EXPECTED))
    def test_premio_count_matches_fixture(self, sorteo_files, name):
        lines = sorteo_files[name].read_text(encoding="utf-8").splitlines()
        _, body = split_header_body(lines)
        assert len(process_body(body)) == EXPECTED[name]["premios"]

    @pytest.mark.parametrize("name", list(EXPECTED))
    def test_no_vendido_count_matches_fixture(self, sorteo_files, name):
        lines = sorteo_files[name].read_text(encoding="utf-8").splitlines()
        _, body = split_header_body(lines)
        premios = process_body(body)

        actual = sum(1 for p in premios if p["vendido_por"] == "NO VENDIDO")
        assert actual == EXPECTED[name]["no_vendido"]

    def test_no_vendido_sets_the_literal_and_nulls_geography(self):
        body = [
            "CENTENARES",
            "05278 P .... 3,000.00",
            "NO VENDIDO",
        ]
        (premio,) = process_body(body)

        assert premio["vendido_por"] == "NO VENDIDO"
        # Explicit None rather than absent — silver is Parquet and the columns must exist.
        assert premio["ciudad"] is None
        assert premio["departamento"] is None

    def test_vendido_por_attaches_to_the_preceding_premio(self):
        # The seller line follows its prize; it must not leak onto the next one.
        body = [
            "00768 P .... 5,000.00",
            "VENDIDO POR VENDOR_001, DE TECULUTÁN, ZACAPA",
            "00987 TT .... 500.00",
        ]
        first, second = process_body(body)

        assert first["vendido_por"] == "VENDOR_001, DE TECULUTÁN, ZACAPA"
        assert second["vendido_por"] is None

    def test_monto_is_float_with_thousands_separator_removed(self):
        body = ["00103 PR .... 1,070.00"]
        (premio,) = process_body(body)

        assert isinstance(premio["monto"], float)
        assert premio["monto"] == 1070.00

    def test_numero_premiado_keeps_leading_zeros(self):
        # It is a ticket identifier, not a quantity. Stored as text so "00046" != 46.
        body = ["00046 P .... 700.00"]
        (premio,) = process_body(body)

        assert premio["numero_premiado"] == "00046"
        assert isinstance(premio["numero_premiado"], str)

    def test_section_labels_and_noise_are_ignored(self):
        body = [
            "CENTENARES",
            "",
            "00046 P .... 700.00",
            "00MIL",
            "VER LISTA DE COMBINACIONES",
        ]
        assert len(process_body(body)) == 1

    def test_orphan_vendido_por_without_a_premio_is_dropped(self):
        # Guards the `last_premio_index is not None` branch: a seller line before any prize
        # must not raise and must not invent a row.
        assert process_body(["VENDIDO POR VENDOR_001, DE ESTA CAPITAL"]) == []

    @pytest.mark.parametrize("name", list(EXPECTED))
    def test_every_premio_has_the_full_key_set(self, sorteo_files, name):
        lines = sorteo_files[name].read_text(encoding="utf-8").splitlines()
        _, body = split_header_body(lines)

        expected_keys = {
            "numero_premiado",
            "letras",
            "monto",
            "vendido_por",
            "ciudad",
            "departamento",
        }
        for premio in process_body(body):
            assert set(premio) == expected_keys

    @pytest.mark.parametrize("name", list(EXPECTED))
    def test_montos_are_never_negative(self, sorteo_files, name):
        lines = sorteo_files[name].read_text(encoding="utf-8").splitlines()
        _, body = split_header_body(lines)
        assert all(p["monto"] >= 0 for p in process_body(body))


# ==========================================================================================
# split_vendido_por_column
# ==========================================================================================
class TestSplitVendidoPorColumn:
    def test_splits_full_three_part_value(self):
        df = pd.DataFrame({"vendido_por": ["VENDOR_001, DE TECULUTÁN, ZACAPA"]})
        out = split_vendido_por_column(df)

        assert out.loc[0, "vendedor"] == "VENDOR_001"
        assert out.loc[0, "ciudad"] == "DE TECULUTÁN"
        assert out.loc[0, "departamento"] == "ZACAPA"

    def test_handles_ciudad_only_rows(self):
        # 143 of 261 seller lines in the fixtures have no departamento — "DE ESTA CAPITAL"
        # is Guatemala City and carries no second comma. This is the common case, not an edge.
        df = pd.DataFrame(
            {
                "vendido_por": [
                    "VENDOR_001, DE TECULUTÁN, ZACAPA",
                    "VENDOR_002, DE ESTA CAPITAL",
                ]
            }
        )
        out = split_vendido_por_column(df)

        assert out.loc[1, "vendedor"] == "VENDOR_002"
        assert out.loc[1, "ciudad"] == "DE ESTA CAPITAL"
        assert pd.isna(out.loc[1, "departamento"])

    def test_all_rows_ciudad_only_leaves_departamento_absent(self):
        # When NO row has a second comma the split produces fewer columns, and the function
        # takes its `shape[1] > 2` branch. Easy to break by "simplifying" the guards away.
        df = pd.DataFrame({"vendido_por": ["VENDOR_001, DE ESTA CAPITAL"]})
        out = split_vendido_por_column(df)

        assert out.loc[0, "ciudad"] == "DE ESTA CAPITAL"
        assert pd.isna(out.loc[0, "departamento"])

    def test_no_vendido_survives_as_the_vendedor_value(self):
        # "NO VENDIDO" has no commas at all, so it lands in `vendedor` with the rest null.
        # Downstream gold queries rely on this exact shape to exclude unsold prizes.
        df = pd.DataFrame({"vendido_por": ["NO VENDIDO", "VENDOR_001, DE ESTA CAPITAL"]})
        out = split_vendido_por_column(df)

        assert out.loc[0, "vendedor"] == "NO VENDIDO"
        assert pd.isna(out.loc[0, "ciudad"])

    def test_original_column_is_removed(self):
        df = pd.DataFrame({"vendido_por": ["VENDOR_001, DE ESTA CAPITAL"]})
        out = split_vendido_por_column(df)

        assert "vendido_por" not in out.columns
        assert {"vendedor", "ciudad", "departamento"} <= set(out.columns)

    def test_whitespace_around_each_part_is_stripped(self):
        df = pd.DataFrame({"vendido_por": ["  VENDOR_001 ,   DE COBÁN ,  ALTA VERAPÁZ  "]})
        out = split_vendido_por_column(df)

        assert out.loc[0, "vendedor"] == "VENDOR_001"
        assert out.loc[0, "ciudad"] == "DE COBÁN"
        assert out.loc[0, "departamento"] == "ALTA VERAPÁZ"

    def test_end_to_end_against_a_real_fixture(self, ordinario_lines):
        """The three functions composed, the way the transformer calls them."""
        _, body = split_header_body(ordinario_lines)
        df = pd.DataFrame(process_body(body)).drop(columns=["ciudad", "departamento"])
        out = split_vendido_por_column(df)

        assert len(out) == EXPECTED["ordinario_3046"]["premios"]
        assert (out["vendedor"] == "NO VENDIDO").sum() == EXPECTED["ordinario_3046"]["no_vendido"]
        # Every non-null vendedor is a placeholder — proof the committed fixture is scrubbed.
        real = out["vendedor"].dropna()
        assert real[~real.str.match(r"^(VENDOR_\d{3}|NO VENDIDO)$")].empty
