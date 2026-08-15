"""Great Expectations suites for the Silver layer (PR-032).

Python is the **source of truth** for these suites. The JSON under
``qa/great_expectations/expectations/`` is generated from the functions here by
``scripts/run_dq.py --sync-suites`` and committed so a reviewer can read the contract
without running anything; ``tests/unit/test_dq_suites.py`` fails if the two drift apart.

Every expectation below was checked against the real Silver dataset before being committed
(111 sorteos / 116,757 premios as of 2026-08-15). That ordering matters: an expectation
that fails on day one turns the PR-033 gate into something people route around, which is
the same failure mode as a canary that silently skips (PR-031).

The builders take no arguments and touch nothing: expectations are passed to the
``ExpectationSuite`` constructor rather than added with ``suite.add_expectation()``, because
``add_expectation`` reaches for an ambient GX data context (it checks whether the suite has
already been persisted) and raises ``DataContextRequiredError`` without one. Building
through the constructor keeps these functions importable and testable on their own.

Two deliberate departures from the roadmap prompt, both because the prompt describes a
schema we do not have:

* **``expect_column_values_to_match_strftime_format`` on ``fecha_sorteo`` is not used.**
  The transformer already calls ``pd.to_datetime(format="%d/%m/%Y")``, so in Silver the
  column is a real ``datetime64`` — there is no string left to match a format against, and
  the strftime expectation would compare against ``"2024-06-01 00:00:00"`` and fail. The
  intent (the date is a parseable, sane date) is covered by a range expectation plus the
  not-null one: an unparseable date arrives as ``NaT``, because the transformer parses with
  ``errors="coerce"``.
* **``expect_column_values_to_be_between`` for ``monto`` lives only on premios.** The prompt
  already flags this — ``sorteos`` has no monto column.
"""

from __future__ import annotations

import datetime as dt

import great_expectations as gx
from great_expectations import expectations as gxe
from great_expectations.core import ExpectationSuite

SORTEOS_SUITE_NAME = "silver_sorteos"
PREMIOS_SUITE_NAME = "silver_premios"

# The 22 departamentos of Guatemala, **spelled the way loteria.org.gt spells them** — which
# is not the way the country spells them. The source writes "ALTA VERAPÁZ" and
# "BAJA VERAPÁZ" with an accent that does not belong on "Verapaz". That is a source typo,
# faithfully carried through the parser, and this set has to encode it: the whole point of
# the expectation is to detect the day the *site* changes, so it must describe what the site
# actually emits, not what is orthographically correct.
#
# Derived by profiling every premios Parquet file in Silver, not typed from a reference
# list. All 22 departamentos are present, and there are exactly 22 distinct values — no
# garbage rows from a bad `vendido_por` split. If a 23rd value ever shows up, either the
# site changed its spelling or `split_vendido_por_column` mis-split a line; both are worth
# blocking Gold over.
#
# NOTE ON NULLS: ~91% of premios rows have a null departamento, because most prizes have no
# "VENDIDO POR" line at all. The roadmap prompt asks for `None` in the value set to allow
# for this. It is not needed — GX column-map expectations exclude nulls from evaluation by
# default — and adding it would be misleading, so nulls are handled by *omitting* a
# not-null expectation on this column rather than by widening the set.
DEPARTAMENTOS = (
    "ALTA VERAPÁZ",
    "BAJA VERAPÁZ",
    "CHIMALTENANGO",
    "CHIQUIMULA",
    "EL PROGRESO",
    "ESCUINTLA",
    "GUATEMALA",
    "HUEHUETENANGO",
    "IZABAL",
    "JALAPA",
    "JUTIAPA",
    "PETÉN",
    "QUETZALTENANGO",
    "QUICHÉ",
    "RETALHULEU",
    "SACATEPÉQUEZ",
    "SAN MARCOS",
    "SANTA ROSA",
    "SOLOLÁ",
    "SUCHITEPÉQUEZ",
    "TOTONICAPÁN",
    "ZACAPA",
)

# Only the two values the header regex `SORTEO (\w+)` has ever produced.
TIPOS_SORTEO = ("ORDINARIO", "EXTRAORDINARIO")

# Bounds for `fecha_sorteo`. The floor is the project's own history: the first sorteo in
# Silver is 2024-06-01, and nothing older will ever be back-filled from the site. The
# ceiling is deliberately far out and deliberately *static* — it exists to catch gross
# corruption (an epoch-zero date, a 2099 typo, a column read at the wrong offset), not to
# assert "not in the future".
#
# A tighter "fecha_sorteo <= today" was considered and rejected. It cannot live in a
# committed suite without the JSON changing every day, so it would have to be injected at
# run time — which splits the suite into a static half and a dynamic half that the drift
# test can no longer compare. The value it would add is small: the transformer parses with
# an explicit `%d/%m/%Y` format and `errors="coerce"`, so a malformed date arrives as NaT
# and is caught by the not-null expectation rather than as a plausible future date.
FECHA_SORTEO_MIN = dt.datetime(2024, 1, 1)
FECHA_SORTEO_MAX = dt.datetime(2035, 1, 1)


def build_sorteos_suite() -> ExpectationSuite:
    """The ``silver_sorteos`` contract: one row per draw, uniquely keyed, correctly dated."""
    expectations = [
        # --- Roadmap-mandated -----------------------------------------------------------
        *(
            gxe.ExpectColumnValuesToNotBeNull(column=column)
            for column in ("numero_sorteo", "fecha_sorteo", "primer_premio")
        ),
        # The single most important expectation in the project. The transformer's idempotency
        # check is "is this sorteo already under silver/sorteos/?" — if that check ever
        # regresses, the same draw is written twice and every Gold aggregate silently
        # double-counts it. Nothing downstream would notice; this does.
        gxe.ExpectColumnValuesToBeUnique(column="numero_sorteo"),
        # Stands in for the prompt's strftime expectation — see the module docstring.
        gxe.ExpectColumnValuesToBeBetween(
            column="fecha_sorteo",
            min_value=FECHA_SORTEO_MIN,
            max_value=FECHA_SORTEO_MAX,
        ),
        # --- Added beyond the prompt ----------------------------------------------------
        # A winning number is a positive integer. Zero or negative means `_to_int64` coerced
        # something unparseable, which means the header regex matched the wrong text.
        *(
            gxe.ExpectColumnValuesToBeBetween(column=column, min_value=1)
            for column in ("primer_premio", "segundo_premio", "tercer_premio")
        ),
        # `tipo_sorteo` is the one string column the transformer never passes through
        # `_to_string()` — its dtype is left to pandas inference (flagged in PR-030's notes).
        # This does not fix the dtype, but it does catch the realistic corruption: the header
        # regex `SORTEO (\w+)` grabbing an unexpected word and quietly seeding a third
        # category into every Gold group-by.
        gxe.ExpectColumnValuesToBeInSet(column="tipo_sorteo", value_set=list(TIPOS_SORTEO)),
        # A ticket cannot expire before the draw it belongs to. Both dates are parsed by the
        # same `%d/%m/%Y` call, so this is the check that catches the two being swapped or
        # the site reordering its header fields — which no single-column check can see.
        gxe.ExpectColumnPairValuesAToBeGreaterThanB(
            column_A="fecha_caducidad",
            column_B="fecha_sorteo",
        ),
        # Guards the empty-input case: an S3 listing that returned nothing would otherwise
        # validate a zero-row frame and report a cheerful green.
        gxe.ExpectTableRowCountToBeBetween(min_value=1),
    ]
    return gx.ExpectationSuite(name=SORTEOS_SUITE_NAME, expectations=expectations)


def build_premios_suite() -> ExpectationSuite:
    """The ``silver_premios`` contract: every prize is attributable, numeric and located."""
    expectations = [
        # --- Roadmap-mandated -----------------------------------------------------------
        *(
            gxe.ExpectColumnValuesToNotBeNull(column=column)
            for column in ("numero_sorteo", "numero_premiado", "monto")
        ),
        gxe.ExpectColumnValuesToBeInSet(column="departamento", value_set=list(DEPARTAMENTOS)),
        # `monto` is built with `_to_float64(default=0.0)`, so an unparseable amount lands as
        # 0 rather than null and slips past the not-null check above. The observed floor is
        # Q500; `min_value=0` is what the prompt asks for and still catches a sign flip.
        gxe.ExpectColumnValuesToBeBetween(column="monto", min_value=0),
        # --- Added beyond the prompt ----------------------------------------------------
        # `letras` is always captured by the body regex, so a null here means a premio row
        # was assembled by something other than that regex.
        gxe.ExpectColumnValuesToNotBeNull(column="letras"),
        # The prize letters are an uppercase code (P, TT, PCR, ...). A regex rather than a
        # value set: 32 distinct combinations appear today and new ones are legitimate, but
        # lowercase or punctuation would mean the line was split wrong.
        gxe.ExpectColumnValuesToMatchRegex(column="letras", regex=r"^[A-Z]+$"),
        gxe.ExpectColumnValuesToBeBetween(column="numero_premiado", min_value=0),
        gxe.ExpectTableRowCountToBeBetween(min_value=1),
    ]
    return gx.ExpectationSuite(name=PREMIOS_SUITE_NAME, expectations=expectations)


#: Suite name -> builder. The runner iterates this, so adding a suite here is enough to get
#: it validated, synced to JSON and covered by the drift test.
SUITE_BUILDERS = {
    SORTEOS_SUITE_NAME: build_sorteos_suite,
    PREMIOS_SUITE_NAME: build_premios_suite,
}
