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
