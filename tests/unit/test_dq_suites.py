"""Tests for the Silver expectation suites (PR-032).

Offline: builds suites and validates hand-made frames. No S3, no network — the S3 side is
``test_dq_runner.py``.

The frames here are deliberately *minimal but schema-true*: same column names and same
dtypes the transformer writes (nullable ``Int64``, ``datetime64``, ``string``), because
several expectations behave differently on a plain ``int64`` column than on the nullable
``Int64`` the pipeline actually produces.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from loteria.dq.runner import validate_dataframe
from loteria.dq.suites import (
    DEPARTAMENTOS,
    PREMIOS_SUITE_NAME,
    SORTEOS_SUITE_NAME,
    SUITE_BUILDERS,
    TIPOS_SORTEO,
    build_premios_suite,
    build_sorteos_suite,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_SUITES = REPO_ROOT / "qa" / "great_expectations" / "expectations"


# ==========================================================================================
# Frame factories
# ==========================================================================================
def make_sorteos(**overrides) -> pd.DataFrame:
    """Two valid Silver sorteos rows. Pass a column name to replace its values."""
    data = {
        "numero_sorteo": pd.Series([3046, 3047], dtype="int64"),
        "tipo_sorteo": pd.Series(["ORDINARIO", "EXTRAORDINARIO"], dtype="string"),
        "fecha_sorteo": pd.to_datetime(["2024-06-01", "2024-06-08"]),
        "fecha_caducidad": pd.to_datetime(["2024-08-30", "2024-09-06"]),
        "primer_premio": pd.Series([12345, 54321], dtype="Int64"),
        "segundo_premio": pd.Series([2222, 3333], dtype="Int64"),
        "tercer_premio": pd.Series([4444, 5555], dtype="Int64"),
        "reintegro_primer_premio": pd.Series([5, 1], dtype="Int64"),
        "reintegro_segundo_premio": pd.Series([2, 3], dtype="Int64"),
        "reintegro_tercer_premio": pd.Series([4, 5], dtype="Int64"),
    }
    data.update(overrides)
    return pd.DataFrame(data)


def make_premios(**overrides) -> pd.DataFrame:
    """Three valid Silver premios rows, including one unsold prize with null geography."""
    data = {
        "numero_sorteo": pd.Series([3046, 3046, 3046], dtype="int64"),
        "numero_premiado": pd.Series([1234, 5678, 9012], dtype="Int64"),
        "letras": pd.Series(["P", "TT", "PCR"], dtype="string"),
        "monto": pd.Series([1000.0, 500.0, 7000350.0], dtype="float64"),
        "vendedor": pd.Series(["UN VENDEDOR", "NO VENDIDO", "OTRO"], dtype="string"),
        # Row 2 is the "NO VENDIDO" shape: ~91% of real premios rows look like this, so a
        # fixture without one would let a stray not-null expectation on departamento pass
        # here and then fail against every real batch.
        "ciudad": pd.Series(["ANTIGUA", None, "COBÁN"], dtype="string"),
        "departamento": pd.Series(["SACATEPÉQUEZ", None, "ALTA VERAPÁZ"], dtype="string"),
    }
    data.update(overrides)
    return pd.DataFrame(data)


def outcome_for(dataset: str, df: pd.DataFrame):
    return validate_dataframe(dataset, df)


def failed_expectations(outcome) -> set[tuple[str, str | None]]:
    return {(f.expectation, f.column) for f in outcome.failures}


# ==========================================================================================
# Shape of the suites
# ==========================================================================================
class TestSuiteDefinitions:
    def test_builders_need_no_ambient_data_context(self):
        """Building a suite must not require ``gx.get_context()`` to have been called.

        ``ExpectationSuite.add_expectation()`` reaches for the global project manager to
        check whether the suite was already persisted, and raises ``DataContextRequiredError``
        in a fresh process. The builders therefore pass expectations to the constructor.
        This test only passes if that stays true — it is the first thing in the module that
        touches GX, so no other test can have created a context for it.
        """
        assert build_sorteos_suite().name == SORTEOS_SUITE_NAME
        assert build_premios_suite().name == PREMIOS_SUITE_NAME

    def test_every_dataset_in_the_registry_has_a_builder(self):
        assert set(SUITE_BUILDERS) == {SORTEOS_SUITE_NAME, PREMIOS_SUITE_NAME}

    @pytest.mark.parametrize(
        ("build", "expected"),
        [
            (
                build_sorteos_suite,
                {
                    ("expect_column_values_to_not_be_null", "numero_sorteo"),
                    ("expect_column_values_to_not_be_null", "fecha_sorteo"),
                    ("expect_column_values_to_not_be_null", "primer_premio"),
                    ("expect_column_values_to_be_unique", "numero_sorteo"),
                },
            ),
            (
                build_premios_suite,
                {
                    ("expect_column_values_to_not_be_null", "numero_sorteo"),
                    ("expect_column_values_to_not_be_null", "numero_premiado"),
                    ("expect_column_values_to_not_be_null", "monto"),
                    ("expect_column_values_to_be_in_set", "departamento"),
                    ("expect_column_values_to_be_between", "monto"),
                },
            ),
        ],
    )
    def test_roadmap_mandated_expectations_are_present(self, build, expected):
        """PR-032's prompt lists these by name. Deviations are documented; deletions are not."""
        actual = {
            (e["type"], e["kwargs"].get("column")) for e in build().to_json_dict()["expectations"]
        }
        assert expected <= actual


class TestDepartamentos:
    def test_there_are_exactly_twenty_two(self):
        assert len(DEPARTAMENTOS) == 22

    def test_no_duplicates(self):
        assert len(set(DEPARTAMENTOS)) == len(DEPARTAMENTOS)

    def test_all_uppercase_and_stripped(self):
        """The parser upper-cases nothing — it splits the site's text as-is."""
        for name in DEPARTAMENTOS:
            assert name == name.upper()
            assert name == name.strip()

    def test_keeps_the_source_typo_in_the_verapaces(self):
        """``VERAPÁZ`` is misspelled *by loteria.org.gt*, and the set must match the source.

        Someone will eventually "fix" these to VERAPAZ. That silently breaks the expectation
        against every real batch, because the site keeps emitting the accent. This test is
        here to make the correction fail loudly instead.
        """
        assert "ALTA VERAPÁZ" in DEPARTAMENTOS
        assert "BAJA VERAPÁZ" in DEPARTAMENTOS
        assert "ALTA VERAPAZ" not in DEPARTAMENTOS


# ==========================================================================================
# Committed JSON vs Python
# ==========================================================================================
class TestCommittedSuitesMatchPython:
    """``qa/great_expectations/`` is generated. Guard it against going stale.

    Without this, editing an expectation in Python and forgetting
    ``python scripts/run_dq.py --sync-suites`` leaves a committed contract that says
    something the pipeline no longer enforces — the most misleading possible state for a
    file whose only purpose is to be read.
    """

    @pytest.mark.parametrize("suite_name", sorted(SUITE_BUILDERS))
    def test_committed_json_is_in_sync(self, suite_name):
        committed = json.loads(
            (COMMITTED_SUITES / f"{suite_name}.json").read_text(encoding="utf-8")
        )
        # Round-trip through json so datetimes and tuples land in the same shape the file
        # holds, then drop the ids `--sync-suites` strips.
        built = json.loads(json.dumps(SUITE_BUILDERS[suite_name]().to_json_dict(), default=str))
        built.pop("id", None)
        committed.pop("id", None)
        for expectation in built.get("expectations", []):
            expectation.pop("id", None)

        assert built == committed, (
            f"{suite_name}.json is out of date — "
            f"run `python scripts/run_dq.py --sync-suites` and commit the result"
        )

    @pytest.mark.parametrize("suite_name", sorted(SUITE_BUILDERS))
    def test_committed_json_carries_no_random_ids(self, suite_name):
        """The ids GX mints are regenerated on every write; committing them means every
        sync produces a whole-file diff."""
        raw = (COMMITTED_SUITES / f"{suite_name}.json").read_text(encoding="utf-8")
        assert '"id"' not in raw


# ==========================================================================================
# Behaviour: silver_sorteos
# ==========================================================================================
class TestSorteosSuiteBehaviour:
    def test_a_clean_frame_passes_every_expectation(self):
        outcome = outcome_for("sorteos", make_sorteos())
        assert outcome.success, failed_expectations(outcome)

    def test_a_duplicated_sorteo_fails(self):
        """The failure this suite exists for: the same draw written to Silver twice."""
        df = pd.concat([make_sorteos(), make_sorteos()], ignore_index=True)
        outcome = outcome_for("sorteos", df)

        assert not outcome.success
        assert ("expect_column_values_to_be_unique", "numero_sorteo") in failed_expectations(
            outcome
        )

    def test_a_null_fecha_sorteo_fails(self):
        """``pd.to_datetime(errors="coerce")`` turns an unparseable date into NaT rather than
        raising, so a site date-format change surfaces here."""
        df = make_sorteos(fecha_sorteo=pd.to_datetime(["2024-06-01", None]))
        outcome = outcome_for("sorteos", df)

        assert ("expect_column_values_to_not_be_null", "fecha_sorteo") in failed_expectations(
            outcome
        )

    def test_an_unknown_tipo_sorteo_fails(self):
        df = make_sorteos(tipo_sorteo=pd.Series(["ORDINARIO", "NAVIDEÑO"], dtype="string"))
        outcome = outcome_for("sorteos", df)

        assert ("expect_column_values_to_be_in_set", "tipo_sorteo") in failed_expectations(outcome)

    def test_expiry_before_the_draw_fails(self):
        """Neither date is individually wrong here — only their relationship is."""
        df = make_sorteos(fecha_caducidad=pd.to_datetime(["2024-01-01", "2024-09-06"]))
        outcome = outcome_for("sorteos", df)

        assert (
            "expect_column_pair_values_a_to_be_greater_than_b",
            "fecha_caducidad",
        ) in failed_expectations(outcome)

    def test_a_zero_winning_number_fails(self):
        """``_to_int64`` coerces unparseable text to NA and then, for keyed columns, to 0."""
        df = make_sorteos(primer_premio=pd.Series([0, 54321], dtype="Int64"))
        outcome = outcome_for("sorteos", df)

        assert ("expect_column_values_to_be_between", "primer_premio") in failed_expectations(
            outcome
        )

    def test_an_epoch_date_fails_the_range(self):
        df = make_sorteos(fecha_sorteo=pd.to_datetime(["1970-01-01", "2024-06-08"]))
        outcome = outcome_for("sorteos", df)

        assert ("expect_column_values_to_be_between", "fecha_sorteo") in failed_expectations(
            outcome
        )

    def test_an_empty_frame_fails_rather_than_passing_vacuously(self):
        """Every column-map expectation is trivially true on zero rows. Without the row-count
        expectation an empty Silver layer would report a clean PASS."""
        outcome = outcome_for("sorteos", make_sorteos().iloc[0:0])

        assert not outcome.success
        assert ("expect_table_row_count_to_be_between", None) in failed_expectations(outcome)


# ==========================================================================================
# Behaviour: silver_premios
# ==========================================================================================
class TestPremiosSuiteBehaviour:
    def test_a_clean_frame_passes_every_expectation(self):
        outcome = outcome_for("premios", make_premios())
        assert outcome.success, failed_expectations(outcome)

    def test_null_departamento_is_allowed(self):
        """~91% of real rows have no geography because the prize has no VENDIDO POR line.

        The roadmap prompt suggests putting ``None`` in the value set for this. It is not
        needed: GX column-map expectations skip nulls. This test pins that behaviour, since
        the suite would be wrong in opposite directions depending on which is true.
        """
        df = make_premios(departamento=pd.Series([None, None, None], dtype="string"))
        outcome = outcome_for("premios", df)

        assert ("expect_column_values_to_be_in_set", "departamento") not in failed_expectations(
            outcome
        )

    def test_an_unknown_departamento_fails(self):
        """A 23rd value means either the site changed spelling or `split_vendido_por_column`
        mis-split a line — both should stop Gold."""
        df = make_premios(
            departamento=pd.Series(["SACATEPÉQUEZ", None, "PETEN"], dtype="string"),
        )
        outcome = outcome_for("premios", df)

        assert ("expect_column_values_to_be_in_set", "departamento") in failed_expectations(outcome)

    def test_a_negative_monto_fails(self):
        df = make_premios(monto=pd.Series([1000.0, -1.0, 7000350.0], dtype="float64"))
        outcome = outcome_for("premios", df)

        assert ("expect_column_values_to_be_between", "monto") in failed_expectations(outcome)

    def test_lowercase_letras_fail_the_regex(self):
        df = make_premios(letras=pd.Series(["P", "tt", "PCR"], dtype="string"))
        outcome = outcome_for("premios", df)

        assert ("expect_column_values_to_match_regex", "letras") in failed_expectations(outcome)

    def test_a_null_monto_fails(self):
        df = make_premios(monto=pd.Series([1000.0, None, 7000350.0], dtype="float64"))
        outcome = outcome_for("premios", df)

        assert ("expect_column_values_to_not_be_null", "monto") in failed_expectations(outcome)

    def test_failures_report_a_bounded_sample_of_offending_values(self):
        """The report is read out of a log line, so it must not embed 100k bad values."""
        df = make_premios(
            numero_sorteo=pd.Series([3046] * 3, dtype="int64"),
            letras=pd.Series(["p"] * 3, dtype="string"),
        )
        outcome = outcome_for("premios", df)
        failure = next(f for f in outcome.failures if f.expectation.endswith("match_regex"))

        assert failure.partial_unexpected
        assert len(failure.partial_unexpected) <= 10


# ==========================================================================================
# The constant the suites lean on
# ==========================================================================================
def test_tipos_sorteo_matches_what_the_parser_can_emit():
    """The header regex is ``SORTEO (\\w+)``; only these two words have ever come out."""
    assert set(TIPOS_SORTEO) == {"ORDINARIO", "EXTRAORDINARIO"}
