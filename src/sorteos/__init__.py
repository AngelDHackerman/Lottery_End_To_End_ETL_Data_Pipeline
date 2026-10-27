"""Official lottery draws, one subpackage per country (docs/uruguay/DESIGN.md, D1).

- core: what knows no country — the polite HTTP client, the bronze store and manifest.
- uy:   Uruguay (DNLQ). A new country is a sibling folder named by its ISO 3166-1 alpha-2
        code; what two countries turn out to share moves up to ``core`` then, not before.

Lives beside ``loteria`` (Santa Lucía) on purpose, not inside it: the Lambda, Glue and DQ
build scripts copy ``src/loteria`` and nothing else, so nothing here can ride into a Santa
Lucía artifact or trigger a redeploy of one (roadmap-uruguay.md, rule 6).
"""
