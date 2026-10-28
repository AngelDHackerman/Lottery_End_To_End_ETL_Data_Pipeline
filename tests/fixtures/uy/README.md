# Uruguay fixtures (www.loteria.gub.uy)

Real pages, fetched 2026-10-04 (two on 2026-10-14, one on 2026-10-16) through `sorteos.core.http_client.PoliteClient` (1 req/s,
identifiable User-Agent) and copied here with `scripts/uy_redact_fixture.py`. The script
replaces every `href` naming `DET_INVALIDAS` with `#privacy-link-removed` and changes
nothing else. Those links point at PDFs with national ID numbers; the PDFs themselves were
never requested. `tests/unit/sorteos/test_uy_privacy.py` fails if any file here names the
pattern or the word "cédula".

Winning coupon numbers stay in bronze only (owner decision C7). Since UY-011.1 the script also
replaces each coupon with a fake of the same shape, numbered per page: `000000001-0`,
`000000002-0`, and so on. Check digits become `0`, and the bare 10-digit form becomes
`0000000001`. The parser still counts the same coupons, and the scanner fails on any
coupon-shaped number that does not start with `000000`. Two files carry fakes:
`extracto_5_de_oro_2007-01-07.html` (2) and `resultados_2016-07-06.html` (3). The real numbers
are still in the git history from before UY-011.1; the owner accepted that rather than
rewriting a protected branch.

The site regenerates every page from its database with today's template, so these are
"the page as served on 2026-10-04", not the original documents. Each page also carries a
"Sorteos para el día de hoy" block dated on the day it was fetched (Domingo 4 de Octubre
de 2026). That block is not the requested draw.

| File | Requested URL | Why it is here |
|---|---|---|
| `resultados_2006-08-11.html` | `ver_resultados.php?vdia=11&vmes=8&vano=2006` | First day with data (found by bisection): Lotería + Quiniela Nocturna only |
| `resultados_2010-09-03.html` | `ver_resultados.php?vdia=3&vmes=9&vano=2010` | Pre-2016 layout: Lotería, Quiniela V+N, Kini |
| `resultados_2016-07-06.html` | `ver_resultados.php?vdia=6&vmes=7&vano=2016` | Post-2016 layout: Quiniela V+N, 5 de Oro, the pozos link. 4 privacy links removed |
| `resultados_2026-10-03.html` | `ver_resultados.php?vdia=3&vmes=10&vano=2026` | A Saturday: Nocturna only. 2 privacy links removed |
| `resultados_2019-09-25.html` | `ver_resultados.php?vdia=25&vmes=9&vano=2019` | An `error` day (fetched 2026-10-16 01:26 UTC, UY-007): AFAL strike, the Vespertina header with no extract code. 48,803 bytes against the backfill's 48,072; its "today" block is dated Jueves 15 de Octubre de 2026. 2 privacy links removed |
| `resultados_2025-12-25.html` | `ver_resultados.php?vdia=25&vmes=12&vano=2025` | A day with no draw: HTTP 200, no game blocks |
| `extracto_5_de_oro_2007-01-07.html` | `extractosweb/5deOro/extracto_5_de_oro.php?vdia=07&vmes=01&vano=2007` | The oldest 5 de Oro in the brief: "SIN ACIERTO", cupones, `Pe?aloza` |
| `extracto_5_de_oro_2025-09-16.html` | `…extracto_5_de_oro.php?vdia=16&vmes=09&vano=2025` | Empty template (a Tuesday): date `//`, pozos `0,00` |
| `extracto_quiniela_vespertina_2007-01-02.html` | `extractosweb/quiniela/vespertina/extracto_QV_S.php?vdia=02&vmes=01&vano=2007` | Quiniela extract with Inicio / Primero / Fin |
| `extracto_quiniela_vespertina_2006-08-10.html` | `extractosweb/quiniela/vespertina/extracto_QV_S.php?vdia=10&vmes=08&vano=2006` | Empty Quiniela template (fetched 2026-10-14): only the `extracto_sin_info.gif` image, no `//` |
| `extracto_quiniela_nocturna_2006-08-10.html` | `extractosweb/quiniela/nocturna/extracto_QN_S.php?vdia=10&vmes=08&vano=2006` | Same for the Nocturna; byte-identical to the not-yet-published page of 2026-10-14 at 18:46 |
| `resultados_2006-08-20.html` | `ver_resultados.php?vdia=20&vmes=8&vano=2006` | UY-022: the 5 de Oro with every pool a bare `$` and every winners cell empty (null, never 0) |
| `resultados_2006-08-31.html` | `ver_resultados.php?vdia=31&vmes=8&vano=2006` | UY-022: the one Quiniela published without its Tómbola (Vespertina), and a Nocturna Tómbola with a repeated number |
| `resultados_2006-12-06.html` | `ver_resultados.php?vdia=6&vmes=12&vano=2006` | UY-022: Pozo de Plata equal to Pozo de Oro, kept as published; Kini block skipped. 2 coupons faked |
| `resultados_2018-12-29.html` | `ver_resultados.php?vdia=29&vmes=12&vano=2018` | UY-022: Lotería code 27, one of the 27-38 that were unknown before. 2 privacy links removed |
| `resultados_2023-09-29.html` | `ver_resultados.php?vdia=29&vmes=9&vano=2023` | UY-022: "Próximo Nocturno: 30 / 09 / 203" (text kept, no date) and a Quiniela with a repeated number. 4 privacy links removed |
| `resultados_2025-02-09.html` | `ver_resultados.php?vdia=9&vmes=2&vano=2025` | UY-022: "12 / /02 / 2025" (a repeated separator, read) and 6 Plata coupons, counted. 1 privacy link removed, 6 coupons faked |
| `extracto_5_de_oro_2006-08-20.html` | `…extracto_5_de_oro.php?vdia=20&vmes=08&vano=2006` | UY-023: pools `0,00` (null) and three empty winners cells, read by cell |
| `extracto_5_de_oro_2025-02-09.html` | `…extracto_5_de_oro.php?vdia=09&vmes=02&vano=2025` | UY-023: pairs with `resultados_2025-02-09.html` for the cross-check (6 Plata coupons). 6 coupons faked |
| `extracto_quiniela_vespertina_2006-08-31.html` | `…extracto_QV_S.php?vdia=31&vmes=08&vano=2006` | UY-023: empty times (`hrs.` alone) and no Tómbola, the same draw as `resultados_2006-08-31.html` |
| `extracto_quiniela_nocturna_2009-08-01.html` | `…extracto_QN_S.php?vdia=01&vmes=08&vano=2009` | UY-023: times out of order (Inicio 21:00, Fin 15:24), kept as published |
| `pozos_5_de_oro_2016-06-01.pdf` | the pozos link of `ver_resultados.php?vdia=1&vmes=6&vano=2016` | UY-024: the first pozos PDF linked from ver_resultados; draw 1847. Copied byte for byte (no coupons, no personal data) |
| `pozos_5_de_oro_2026-10-18.pdf` | the pozos link of `ver_resultados.php?vdia=18&vmes=10&vano=2026` | UY-024: the latest in bronze; draw 2920 |
