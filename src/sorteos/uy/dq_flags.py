"""The closed catalog of ``dq_flags`` for Uruguay (DESIGN.md, D22 and P13).

Only these names are valid. The silver writer rejects any other, or one put on a table that is
not its own, so a flag with a typo can never reach silver unseen by the gold filters. Adding a
flag means changing DESIGN.md's catalog, this dict and its test, in the same PR: the test reads
the catalog table of DESIGN.md and compares.
"""

from __future__ import annotations

POZO_PLATA_EQUALS_ORO = "pozo_plata_equals_oro"
AMOUNT_SOURCES_DIFFER = "amount_sources_differ"
NEXT_DRAW_UNPARSED = "next_draw_unparsed"
NEXT_DRAW_IMPLAUSIBLE = "next_draw_implausible"
DRAW_NUMBER_INFERRED = "draw_number_inferred"
TOMBOLA_REPEATED_NUMBER = "tombola_repeated_number"
TOMBOLA_NOT_FROM_QUINIELA = "tombola_not_from_quiniela"
TIMING_OUT_OF_ORDER = "timing_out_of_order"  # owner, UY-023
DRAW_NUMBER_OUT_OF_SEQUENCE = "draw_number_out_of_sequence"  # owner, UY-024

# flag -> the silver table it goes on
CATALOG = {
    POZO_PLATA_EQUALS_ORO: "prizes",
    AMOUNT_SOURCES_DIFFER: "prizes",
    NEXT_DRAW_UNPARSED: "draws",
    NEXT_DRAW_IMPLAUSIBLE: "draws",
    DRAW_NUMBER_INFERRED: "draws",
    TOMBOLA_REPEATED_NUMBER: "draws",
    TOMBOLA_NOT_FROM_QUINIELA: "draws",
    TIMING_OUT_OF_ORDER: "draws",
    DRAW_NUMBER_OUT_OF_SEQUENCE: "draws",
}
