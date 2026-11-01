# Roadmap — Loterías de Uruguay (extensión del proyecto, beta)
**Owner:** Angel Hernandez
**Brief de origen:** [`docs/uruguay/BRIEF.md`](./docs/uruguay/BRIEF.md)
**Rama base:** `loteria-uruguaya-test` (hace de `master` para esta extensión hasta la fase de merge)
**Última actualización:** 2026-11-01 (UY-030.1 merged; UY-030.2 en revisión)

> Plan de ejecución de la extensión a Uruguay (DNLQ, `www.loteria.gub.uy`). El roadmap principal
> ([`roadmap.md`](./roadmap.md)) sigue siendo el de Santa Lucía; este archivo **no** lo reemplaza
> y la rama beta **no** lo edita (ver regla 6).
>
> **Objetivo:** ingesta, calidad de datos y análisis descriptivo (auditoría de aleatoriedad) de
> los sorteos oficiales de Uruguay. **No** es predecir sorteos. Lo que vale para el portafolio es
> ingerir una fuente real sin documentación, el backfill, la validación y un diseño extensible
> (un adaptador por juego, configuración por YAML y después otros países).
>
> **Alcance v1, por prioridad:** 1) 5 de Oro + Revancha · 2) Quiniela + Tómbola Vespertina ·
> 3) Quiniela + Tómbola Nocturna. **No existe un sorteo matutino.** Si aparece "matutina", es un
> error y significa Nocturna.
> **Fuera de v1:** Lotería Uruguaya, Kini (último sorteo publicado: 2013-12-27, verificado en UY-006), "4 de la Suerte" y otros países.

---

## Reglas de trabajo

1. **Un PR por cambio lógico.** Ramas `feat/UY-NNN-slug` (o `docs/`, `fix/`) creadas **desde
   `loteria-uruguaya-test`**, con el PR **hacia `loteria-uruguaya-test`**. Nunca hacia `master`
   antes de la Fase 6.
2. **Nunca apilar PRs.** Es la misma lección de `master` (#37→#40, agosto de 2026): GitHub no
   cambia la base del PR cuando la rama base se fusiona y se borra.
3. **Cada PR actualiza el Tracker** al final de este archivo (estado y enlace).
4. **Verificado / observado / hipótesis.** Toda afirmación sobre la fuente lleva una de esas tres
   etiquetas. Si algo contradice el brief, se reporta en FINDINGS.md en vez de corregirlo en
   silencio.
5. **No se hardcodean rangos ni reglas de juego** sin confirmarlos en resoluciones o en datos.
   Van en `game_rules` con su vigencia.
6. **Santa Lucía no se toca durante la beta.** Ni `src/loteria/`, ni `terraform/`, ni
   `roadmap.md`, ni `DoD.md`. El código nuevo vive en su propio paquete. Los únicos archivos
   compartidos que se pueden editar son `pyproject.toml`, `Makefile` y `.gitignore`, siempre de
   forma aditiva. Así el merge final no tiene conflictos semánticos con el roadmap principal.
7. **Mantener la rama al día:** `git merge master` hacia `loteria-uruguaya-test` cada vez que
   `master` reciba un PR que toque archivos compartidos. Es un merge y no un rebase, porque la
   rama está publicada.
8. **Privacidad (no negociable):** nada que coincida con `DET_INVALIDAS` se pide, se descarga, se
   parsea, se guarda ni se registra en logs. El guard existe **antes** de la primera petición
   (UY-001). Cualquier decisión nueva sobre datos personales se le pregunta al owner antes de
   implementarla.
9. **Cortesía con el sitio:** User-Agent identificable con contacto, **1 req/s global**, backoff
   ante 429/5xx, y nunca volver a pedir algo que ya está en caché.
10. **Mutaciones en AWS (Fase 5):** cada apply necesita el visto bueno explícito del owner, igual
    que en `master`.

---

## Contradicciones y huecos del brief (resueltos aquí o abiertos)

El brief pide reportar lo que se contradice. Esto salió al leerlo junto con el repo:

| # | Qué dice el brief | Problema | Resolución propuesta |
|---|---|---|---|
| C1 | "No modifiques el repo de Santa Lucía" | La extensión vive **en el mismo repo**, en una rama que después se fusiona con `master`. | Regla 6: paquete propio y cero cambios en el código o la infraestructura de Santa Lucía hasta la Fase 6. |
| C2 | Barrido de capa 1 "paralelizable con pocos workers" + "máximo 1 req/s" | Si el límite de 1 req/s es global, más workers no aceleran nada (~7.200 días ≈ 2 h de todos modos) y solo complican el rate limiter. | Un solo worker y un rate limiter global. Paralelizar solo el parseo, que no toca la red. |
| C3 | "Bronce: solo de sorteos reales" + "nunca volver a pedir lo cacheado en bronce" | Un día `no_draw` no queda en bronce, así que se volvería a pedir en cada re-ejecución del backfill. | La **caché es el manifiesto**, no bronce. Un día con `no_draw` confirmado no se vuelve a pedir. Bronce guarda solo sorteos reales. |
| C4 | "Guardar el HTML crudo con fecha de descarga" | El HTML se regenera desde la BD con la plantilla actual, así que dos descargas del mismo día pueden diferir solo en la plantilla. | `content_hash` en el manifiesto más un hash de la **porción de datos** parseada. Un cambio de plantilla no cuenta como cambio de datos. |
| C5 | Los horarios "Inicio/Fin/Primero" de la Quiniela | Uruguay eliminó el horario de verano en 2015. Antes de esa fecha la hora local tenía dos offsets. | `draw_timing` guarda la hora local más la zona `America/Montevideo` (el offset se deriva) y nunca un offset fijo de -03:00. **Resuelto en UY-010:** las tres horas van como columnas de `draws` (propuesta P2 de DESIGN.md, sin tabla `draw_timing`) junto con `timezone`. |
| C6 | Código destinado a Glue | Glue Python Shell llega como máximo a 3.9 (PR-020, PR-050). Si el parser de UY corre ahí, ruff no debe "modernizarlo". | Decidir el runtime de destino en UY-010, **antes** de escribir los parsers. Si es Glue 3.9, ampliar el guard de PR-050 al paquete nuevo. **Decidido por el owner (2026-10-16, UY-010):** Lambda con Python 3.12 para el extractor y el transform. Glue Python Shell queda descartado, así que el guard de 3.9 no se amplía. |
| C7 | Los fixtures del brief incluyen números de cupón (`#########-#`) | No identifican a una persona, pero el brief exige preguntar cualquier decisión nueva sobre datos personales. | **Decisión del owner (2026-10-15, UY-007):** los números de cupón se quedan **solo en bronce**. No entran en plata, porque no aportan análisis, pero tampoco se descartan. Plata guarda el estado del premio (con ganadores, "Sin Aciertos" o vacío). **Y la cantidad (owner, 2026-10-16, UY-010):** plata guarda cuántos cupones ganaron en cada premio (`0` con "Sin Aciertos", nulo con la celda vacía), para estudiar qué tan seguido se reparte un pozo. |
| C8 | "El sorteo más antiguo… 07/01/2007" y el selector del sitio (2007–2026) | **Verificado 2026-10-04:** `ver_resultados.php` acepta 2006, y el primer día con datos es el **11/08/2006** (Lotería + Quiniela Nocturna), hallado por bisección. Antes de esa fecha la página sale vacía. | El backfill arranca el 2006-08-01, y el manifiesto deja registrado dónde empieza la historia. |
| C9 | "Después de ~2010 algunas URLs descargan un PDF" | **Verificado:** el `MostrarExtracto()` del sitio cambia al PDF estático `/extractosweb/{aaaammdd}{o\|v\|n\|l}.pdf` desde el **30/11/2018**, no en 2010. Ese PDF responde 404 cuando no hubo sorteo, y el extracto PHP sigue respondiendo para todas las fechas. | Las dos son fuentes de bronce separadas (`extractos` y `pdf`). |
| C10 | 5 de Oro "miércoles y domingo" | **Verificado:** 261 de 2.072 sorteos (12,6%) caen otro día, sobre todo jueves (186) y lunes (75), por feriados, paros o fútbol (informado por el owner). | El sorteo esperado es el "Próximo sorteo" que anunció el anterior (acierta en el 98,3%), con una tolerancia de +3 días. Ver FINDINGS.md. |
| C11 | El número de sorteo como clave natural y detector de huecos | **Verificado:** no se publica ni en `ver_resultados` ni en el extracto. Solo está en el PDF de pozos (desde ~2016). | La clave es la fecha y el juego. Los huecos se detectan con "Próximo sorteo" y `calendar_events`. |
| C12 | Montos en estilo EE.UU. "en el HTML de 2016" | **Verificado:** `ver_resultados` usa estilo EE.UU. desde 2006 y el extracto usa estilo uruguayo en todas las épocas. | Un parser de montos por fuente, no por época. |
| C13 | Kini: "último sorteo 31/01/2014" | **Verificado (UY-006):** el último sorteo publicado es el **2013-12-27**, y el primero en el sitio el 2006-08-15. | El Kini queda como UL2 con esas fechas. Su bloque ya está completo en el bronce de `ver_resultados`. |
| C14 | Lotería Uruguaya: "frecuencia mensual" (dato del owner, no verificado) | **Verificado (UY-006):** casi semanal hasta 2012 (40 a 43 sorteos al año), una transición en 2013 y **mensual desde 2014**, casi siempre los viernes. | Cuando llegue UL1, el calendario de la Lotería sale de los datos y no se supone mensual. |
| C15 | 5 de Oro: "fuentes de terceros indican 01–48" | **Verificado (UY-004, UY-007):** 01–44 hasta el 2014-03-16 y 01–48 desde el 2014-03-19 (As. 176/2014). El Decreto 635/989 lo creó con 01–36, y el cambio a 01–44 no tiene resolución encontrada. | `game_rules` lleva el rango con vigencia. Un 45 antes del 2014-03-19 es un error de datos. |

---

# Fase 0 — Preparación de la rama

## UY-000 — Higiene de la rama beta
**Objetivo:** dejar la rama lista para recibir PRs.

- Publicar la rama: `git push -u origin loteria-uruguaya-test`. Hoy existe solo en local y es
  idéntica a `master`.
- Mover el brief a `docs/uruguay/BRIEF.md` y actualizar el enlace del encabezado de este archivo.
- Borrar `docs/runbooks/prompt_claude_code_loterias_uruguay.md:Zone.Identifier` (es un metadato de
  Windows y no tiene contenido) y agregar `*:Zone.Identifier` a `.gitignore`.
- `.gitignore`: agregar `/data/uy/`. Es la caché local de bronce y el manifiesto, y **nunca** se
  commitea. Lo que sí se commitea son los fixtures seleccionados en `tests/fixtures/uy/`.
- Commitear este roadmap.
- (Opcional) Proteger la rama en GitHub para que solo acepte cambios por PR. El CI ya corre en
  cualquier `pull_request`, así que los PRs hacia la rama beta quedan cubiertos sin tocar
  `ci.yml`.

**Aceptación:** la rama está en origin, `git status` queda limpio y este archivo está en el árbol.

> **Hecho 2026-10-05:** la rama se publicó **tal cual**, con UY-001 adentro (commit directo
> `ad6bf1f`, sin PR, por decisión del owner). Las líneas de `.gitignore` y el roadmap ya habían
> entrado con ese commit, así que este PR solo mueve el brief, borra el `Zone.Identifier` (estaba
> ignorado y no versionado, se borró solo del disco) y pone al día el Tracker. Desde el 2026-10-05
> `master` y `loteria-uruguaya-test` están protegidas por el ruleset "Protect-master": todo entra
> por PR, con los 7 checks obligatorios.

---

# Fase 1 — Exploración y análisis (es la "Fase 0" del brief)

Sondeos desde **local** con scripts desechables. El único código que sobrevive es el cliente HTTP
de UY-001. **Entregable de la fase:** `docs/uruguay/FINDINGS.md`. Cada pregunta lleva URL, fecha
consultada, código HTTP, cabeceras relevantes, un fragmento mínimo y su etiqueta
(verificado/observado/hipótesis).

Las preguntas abiertas del brief, mapeadas a los PRs (en negrita las que afectan a los juegos
principales):

| Pregunta | Tema | PR |
|---|---|---|
| **Q1** | ¿Aparece el 5 de Oro en el HTML estático de `ver_resultados` (miércoles y domingo, 2007–2026)? ¿Con qué campos? | UY-002 |
| **Q2** | ¿Qué devuelve una fecha sin sorteo? ¿Desde cuándo hay Quiniela en fin de semana? | UY-002 |
| **Q3** | ¿Cuál es la fecha más antigua de cada juego en `ver_resultados` y en `extractosweb`? | UY-002 + UY-003 |
| Q4 | Ruta de los extractos de Lotería Uruguaya y Kini | UY-006 |
| **Q5** | PDF: `Content-Type`, `Content-Disposition`, si es la misma URL, y si HTML y PDF coinciden (~30 fechas) | UY-003 |
| Q6 | Frecuencia real de la Lotería Uruguaya | UY-006 |
| **Q7** | Encoding de cada fuente | UY-002 + UY-003 |
| **Q8** | Rango válido del 5 de Oro y versiones de las reglas | UY-004 |
| Q9 | Términos de uso y pie legal | UY-004 |
| Q10 | ¿Sirve `ver_estadisticas` como control cruzado? ¿Tiene datos descargables? | UY-004 |
| — (nueva) | ¿El sitio bloquea IPs de AWS o a quien no está en Uruguay? | UY-005 |

## UY-001 — Cliente HTTP cortés y guard de privacidad (antes de cualquier petición)
**Objetivo:** que sea imposible pedir una URL excluida, incluso desde un script desechable.

- `src/<paquete_uy>/http_client.py` (el nombre definitivo del paquete se fija en UY-010; mientras
  tanto `src/loteria_uy/`):
  - User-Agent con contacto, un token bucket global de 1 req/s, y backoff exponencial con jitter
    ante 429/5xx (con tope de reintentos).
  - **Blocklist por patrón** (`DET_INVALIDAS`, sin distinguir mayúsculas). Se revisa sobre la URL
    pedida **y sobre cada salto de redirección** (`allow_redirects=False` con los saltos manejados
    a mano), y lanza una excepción **antes** de abrir el socket.
  - Caché en disco indexada por URL normalizada, en `data/uy/cache/`. Una URL cacheada no vuelve
    a la red.
  - Los logs nunca imprimen el cuerpo de la respuesta. Una URL bloqueada se registra como
    `blocked_url_pattern=DET_INVALIDAS`, sin la URL completa.
- Tests en `tests/unit/uy/test_http_client.py`:
  - Las tres URLs excluidas del brief (como strings, nunca pedidas) disparan el bloqueo con la red
    simulada. El test falla si llega a hacerse **cualquier** llamada de red.
  - Una redirección que termina en `DET_INVALIDAS` también se bloquea.
  - `RES_INFORMACION_DE_POZOS` sí pasa.
  - Un scanner de fixtures: ningún archivo en `tests/fixtures/uy/` contiene `DET_INVALIDAS` ni
    `Cédula`/`Cedula`.
- `pytest`: agregar `--cov=src/loteria_uy` **sin** bajar el gate de 98. El paquete nuevo entra
  con su cobertura completa o el gate lo marca.

> **Hecho 2026-10-04, adelantado a pedido del owner:** el scraper de bronce se construyó antes de
> G1 y cubre solo bronce (el crudo); los parsers siguen esperando G2. Además del cliente, ya
> existen `sources.py`, `classify.py`, `bronze.py` (con el manifiesto en SQLite), `backfill.py`,
> los targets `make uy-pilot` / `uy-backfill` / `uy-report`, 77 tests (`loteria_uy` al 100%) y
> 8 fixtures reales con los `href` de privacidad reemplazados (`scripts/uy_redact_fixture.py`). El
> backfill completo desde 2006-08-01 arrancó ese mismo día, a 1 req/s.

**Aceptación:** los tests pasan, el gate de 98 se mantiene y no se hizo ninguna petición real
durante el PR.
**Fuera de alcance:** parsers y almacenamiento.

## UY-002 — Sondeo de `ver_resultados.php` (Q1, Q2, Q3, Q7)
**Objetivo:** confirmar que la capa 1 (una petición por día con todos los juegos) es viable para
los tres juegos principales.

- Muestra estratificada de unas 100 peticiones (~2 min a 1 req/s):
  - por cada año de 2007 a 2026: un miércoles, un domingo, un día hábil y un sábado;
  - las fechas de las resoluciones (24/09/2014, 17/12/2014, 26/06/2015, 26/08/2015 y 27/08/2015,
    23/12/2015);
  - la frontera de layout de julio de 2016 (fines de junio frente a principios de julio);
  - 2007-01-01 a 2007-01-10, para encontrar la fecha más antigua.
- Para cada respuesta: cabeceras (`Content-Type` y charset), encoding real (Q7), juegos presentes,
  campos del 5 de Oro (Q1), y qué devuelve un día sin sorteo (Q2).
- Bisección para encontrar **cuándo empieza la Quiniela en fin de semana** (Q2). Cuesta unas
  12 peticiones.
- Guardar como fixtures solo las páginas representativas, con un README que diga de dónde salió
  cada una y cuándo se descargó.

**Aceptación:** las secciones Q1, Q2, Q3 (parte de `ver_resultados`) y Q7 están en FINDINGS.md.

## UY-003 — Sondeo de `extractosweb/*` y del PDF (Q3, Q5, Q7)
**Objetivo:** saber qué aporta la capa 2 y si el PDF es la misma fuente con otro formato.

- Las sondas del brief (5 de Oro 07/01/2007, Quiniela V/N 02/01/2007): ¿traen datos o la plantilla
  vacía?
- Unas 30 fechas entre 2007 y hoy, por juego: `Content-Type`, `Content-Disposition`, si la URL es
  la misma o hay redirección, y desde qué fecha deja de servirse HTML (Q5).
- Comparar HTML con PDF campo por campo (números, pozos, cupones, horas) en las fechas donde
  existen los dos.
- Plantilla vacía: confirmar los marcadores (fecha `//`, pozos `0,00`, sin bolillas). Son la base
  del estado `no_draw`.
- **`not_yet_published`:** sondear la fecha de un sorteo antes y después de su publicación. Hoy
  (domingo 2026-10-04) hay 5 de Oro a las ~22:00 hora de Uruguay. La Quiniela es diaria.
- El PDF de pozos (`ORO_06072016_RES_INFORMACION_DE_POZOS.PDF`): verificar que el texto se puede
  extraer y elegir la biblioteca (pdfplumber o pypdf).

**Aceptación:** Q3 (parte de `extractosweb`) y Q5 están en FINDINGS.md, con la tabla de
diferencias entre HTML y PDF.

## UY-004 — Metadatos oficiales y reglas (Q8, Q9, Q10)
**Objetivo:** juntar las fuentes de `game_rules` y `calendar_events`.

- `ver_calendario.php`: formato, años cubiertos, y si sirve para generar el calendario esperado.
- `ver_estadisticas.php`: qué publica y si se puede descargar. Sirve como control cruzado (Q10).
- Lista de resoluciones: inventariar las de suspensiones o traslados y los cambios de reglas
  (2012, 2014 As 176/2014, 2019, 2020). Con eso se arma el **borrador** de `game_rules`, con
  vigencias y el rango del 5 de Oro (Q8), y de `calendar_events`, cada fila con su URL.
- Términos de uso y pie legal (Q9). Se transcriben y se citan, **sin sacar conclusión legal**.

**Aceptación:** Q8, Q9 y Q10 están en FINDINGS.md, con un CSV borrador de reglas y eventos que
cita la fuente de cada fila.

## UY-005 — ¿Se puede llegar al sitio desde AWS?
**Objetivo:** reducir el riesgo de la Fase 5 a tiempo. Santa Lucía necesitó un proxy con geo GT
por Cloudflare, y si el sitio de Uruguay bloquea IPs de AWS, cambia el diseño del extractor.

- Una petición a la home y otra a un extracto desde **CloudShell en us-east-1**, con el mismo
  User-Agent. No es una mutación de AWS, pero la corre el owner.
- Si responde 403 o un challenge, probar desde `sa-east-1` (São Paulo) antes de pensar en un
  proxy.

**Aceptación:** el resultado queda en FINDINGS.md como verificado. Además decide si el PDF del extracto se
baja como respaldo: sí sin proxy, no con proxy (decisión del owner en UY-003).

## UY-006 — (Secundario, con tiempo acotado) Lotería Uruguaya y Kini (Q4, Q6)
Un máximo de media sesión. Ruta del extracto (el enlace apunta a `#`, así que hay que buscar el JS
con DevTools) y la frecuencia real. **Nada de implementación.** Se hace después de UY-002 a
UY-005 y solo si no bloquea nada.

## UY-007 — Cierre de la exploración
- Consolidar FINDINGS.md: una tabla resumen por pregunta (etiqueta y PR), las contradicciones
  nuevas con el brief, y las decisiones pendientes para el owner (incluida C7).
- Actualizar la sección de Contradicciones de este archivo.

> 🚦 **Gate G1:** el owner revisa FINDINGS.md. Sin esa revisión no empieza la Fase 2.

---

# Fase 2 — Diseño (es la "Fase 1" del brief; requiere aprobación)

## UY-010 — Esquema canónico, paquete y adaptadores
`docs/uruguay/DESIGN.md`:
- **Nombre y forma del paquete.** Recomendación: un núcleo agnóstico al país (cliente HTTP,
  manifiesto, bronce, validaciones) más adaptadores por país y juego. Por ejemplo
  `src/sorteos/core/` y `src/sorteos/uy/`. Se decide aquí porque renombrarlo después del backfill
  sale caro.
- **Runtime de destino** (C6): ¿extractor y transform en Lambda 3.12, o el transform en Glue
  Python Shell 3.9? Con unos 7.000 días de datos chicos, Lambda probablemente alcanza para todo,
  pero eso se decide con los tamaños medidos en la Fase 1.
- **Plata:** `draws`, `draw_numbers` (formato largo: tipo de bolilla, posición, número como texto
  con ceros, `is_replacement`), `prizes` (`Decimal`), `draw_timing`, `game_rules` (con vigencia),
  `calendar_events` (con URL de la resolución). Claves naturales: la fecha y el turno, y el número
  de sorteo cuando exista. Columnas de linaje como en PR-045.
- **Formato YAML por juego:** endpoints, parámetros, épocas de parser con su vigencia, reglas
  referenciadas a `game_rules`, y horarios.
- **Parsers versionados por época:** 2007 → 2016-06, desde 2016-07, extractos HTML y PDF. Las
  fronteras salen de FINDINGS.md, no del brief.
- **Montos:** un parser por fuente (`42.501.146,34` frente a `35,409,043.86`), siempre `Decimal`.
  Nunca adivinar el formato a partir del valor.

## UY-011 — Ingesta, pruebas y riesgos
- **Manifiesto:** fecha, fuente, URL, HTTP status, estado lógico (`draw`, `no_draw`,
  `not_yet_published`, `error`), hashes (C4), `fetched_at` y versión del parser. Transiciones: un
  `not_yet_published` se reintenta durante N días antes de confirmar `no_draw`.
- **Backfill:** primero la capa 1 completa y después la capa 2 solo donde la capa 1 no alcanza.
  Es reanudable e idempotente, con un worker (C2).
- **Incremental:** Quiniela después de ~15:30 y ~21:30 hora de Uruguay. 5 de Oro después de
  ~22:30 los miércoles y domingos. Una revisión al día siguiente para feriados y traslados.
- **Plan de pruebas:** fixtures reales para los casos límite del brief (página vacía, fecha `//`,
  "Sin Aciertos" frente a vacío, `separador`, `?` por encoding, repetidos en la Quiniela,
  `gif_trasparente`, "Setiembre"), más tests de propiedades de las reglas (la Tómbola tiene
  20 números distintos, la Quiniela tiene 20 posiciones).
- **DQ:** suites de GX para la plata de UY, al estilo de PR-032.
- **Riesgos y supuestos** que la Fase 1 no pudo confirmar.

> 🚦 **Gate G2:** el owner aprueba DESIGN.md. Sin esa aprobación no hay código de producción.

---

# Fase 3 — Construcción en local

> **G2 aprobado por el owner el 2026-10-25** (#111). Esta tabla reemplaza a la que se escribió
> antes del diseño. Cada fila cita lo que la decide en [`DESIGN.md`](docs/uruguay/DESIGN.md)
> (decisiones D, propuestas P aprobadas). El orden importa: cada PR usa lo del anterior, y ninguno
> se apila sobre otro sin fusionar.

| PR | Qué | Lo que lo decide | Aceptación |
|---|---|---|---|
| UY-020 | **Esqueleto del paquete, YAML y registro de juegos.** `src/sorteos/core/` y `src/sorteos/uy/`; un YAML por juego validado con dataclasses propias; `game_rules` y `calendar_events` pasan de `docs/uruguay/drafts/` a `src/sorteos/uy/reference/`; el código de `src/loteria_uy/` se muda sin cambiar su comportamiento; extra `uy` en `pyproject.toml` (`pyyaml`, `pdfplumber`) | D1, D4, P4, P5, la migración de DESIGN | Los 53 tests de hoy pasan contra el paquete nuevo; un test de oro compara las URLs que arma el YAML con las del cliente viejo; el guard `DET_INVALIDAS` sigue en el código |
| UY-021 | **Manifiesto como interfaz.** `Manifest` como `Protocol` con SQLite detrás; el estado efectivo; la regla de las 3 fallas iguales; `manual_overrides.csv` con los 4 días del paro de 2019 | D8–D12, P8, P9 | Los 35 PDF de pozos y los 4 días del paro dejan de pedirse según la regla; el manifiesto actual se lee sin migrarlo |
| UY-022 | **Un solo parser de `ver_resultados`** para 2006–2026, con los tres juegos | D3, D5, P1, P6 | Fixtures nuevos de pruebas y riesgos (Quiniela con repetidos, Tómbola de 2006, "Próximo" raros); ignora "Sorteos para el día de hoy" |
| UY-023 | **Parsers de los extractos PHP** del 5 de Oro y de la Quiniela, con sus horarios | P2, D6, D7 | Celda vacía frente a "Sin Aciertos"; horas locales con `timezone` |
| UY-024 | **Parser del PDF de pozos** (el número de sorteo) y su formato de montos en `core/money.py` (los estilos `us` y `uy` llegaron en UY-022) | D6, C11 | Montos por fuente con su regex estricta; vacío = nulo; un PDF de 2016 y uno de 2026 como fixtures |
| UY-025 | **Escritor de plata** (Parquet por año) con flags y cuarentena | D17, D21, D22, P7, P13 | Solo los 9 flags del catálogo (`timing_out_of_order` se sumó en UY-023 y `draw_number_out_of_sequence` en UY-024); P7 para la Tómbola; el número de sorteo inferido con su flag; nada de columnas con tipo Parquet `Null` |
| UY-026 | **Suites de GX** en un job aparte, con GX empaquetado como wheels | D20, P14 | Las 13 expectativas de partida de DESIGN, más filas y linaje de `master` (owner, 3a), corridas contra plata real antes de entrar; versión fija y suites versionadas. El job de Glue y la medición del arranque pasan a la Fase 5 (owner, 1a) |
| UY-027 | **CLI y targets de Make:** `uy-backfill`, `uy-incremental`, `uy-report` y `uy-properties` | D16, D23, P11, P12 | `uy-incremental` mira 7 días más las claves no finales y pide las cuatro fuentes; todo se puede reanudar |
| UY-028 | **Detector de huecos:** `expected_draws()` en `core/gaps.py` y la tabla `draw_gaps` | D13–D15, P10 | Reproduce sobre el bronce el 99,81 % / 99,98 % / 99,97 % de DESIGN, con el 2006-08-27 como único hueco abierto |

---

# Fase 4 — Pruebas en local (backfill y análisis)

| PR | Qué | Criterio |
|---|---|---|
| UY-030 | **Reconciliación de toda la historia** (UY-030 y UY-031 juntos: owner, 2026-11-01) | Conteos por juego y mes contra el calendario esperado. Cada hueco queda explicado por `calendar_events` o sigue abierto. Continuidad del número de sorteo, comparación con `ver_estadisticas`, tasa de cuarentena. El tiempo de parseo de cada año (D18). |
| ~~UY-031~~ | Se juntó con UY-030 | El bronce completo existe desde UY-001 y la plata se escribe entera desde UY-025.3, así que no hay un piloto que correr antes: UY-030 reconcilia toda la historia. |

> **UY-030 en dos PRs (owner, 2026-11-01):** **UY-030.1** `make uy-reconcile`, que lee solo
> la plata y no hace peticiones (1a), más el tiempo por año en `uy-silver` (3a) · **UY-030.2**
> `ver_estadisticas`: un `post()` en el cliente cortés y unas 12 consultas con los valores que
> ofrece el formulario (6a), guardadas en bronce y sumadas al reporte.
| UY-032 | **Oro local** (SQL portable a Athena/Trino, ejecutado con DuckDB o pandas) | Chi-cuadrado por dígito y por posición, tasa de repetidos frente al ~17% esperado, reemplazos de la Tómbola frente a ~1,8, frecuencias del 5 de Oro por versión de reglas, dinámica de los pozos, puntualidad. Cada métrica dice qué esperaba y qué observó. |
| UY-033 | **Incremental en local durante ~2 semanas** | Cubre transiciones `not_yet_published` → `draw`, al menos un feriado y ambos turnos. Cero peticiones duplicadas según el manifiesto. |

> 🚦 **Gate G3:** los datos locales son confiables (la reconciliación está limpia o cada
> diferencia está explicada) y el owner decide pasar a la nube.

---

# Fase 5 — Deploy en la nube

Se reutilizan los módulos de Terraform de `master`. **Ningún recurso de Santa Lucía cambia**:
el `terraform plan` de cada PR solo agrega recursos de UY. Cada apply necesita el visto bueno del
owner.

| PR | Qué | Lecciones de `master` que aplican |
|---|---|---|
| UY-040 | Decisiones de la nube | ¿Buckets nuevos o el prefijo `country=uy` en los existentes? Una base de Glue/LF propia (`lottery_uy`). ¿Hace falta proxy? (depende de UY-005). Schedules en `America/Montevideo`. |
| UY-041 | Almacenamiento, IAM y Lake Formation | LF: grants por tabla además de por base, los permisos explícitos (nunca `ALL`), y `lakeformation:GetDataAccess`. El deny del bucket y el versionado afectan cómo se purga oro. |
| UY-042 | **Subir el bronce local a S3** (no se vuelve a scrapear) y correr el transform en la nube | Reconciliar la plata de la nube con la local, fila por fila, por hash. |
| UY-043 | Orquestación incremental (EventBridge + Step Functions) | El polling del crawler usa `LastCrawl` y no solo `State==READY`. Validar el ASL renderizado. Los grupos de logs se declaran antes de que alguien escriba en ellos. |
| UY-044 | Oro en Athena con publicación atómica | El patrón de PR-042 (construir al lado y hacer swap) con TableInput como allowlist. |
| UY-045 | Observabilidad: alarmas de "sorteo faltante" y un canario | Las trampas de las alarmas: la evaluación tiene un tope de 7 días, y 0 no es lo mismo que "sin dato". |

> 🚦 **Gate G4:** dos semanas de incremental en la nube sin intervención manual.

---

# Fase 6 — Merge con el proyecto principal

## UY-050 — `loteria-uruguaya-test` → `master`
- `git merge master` final hacia la rama beta y resolución de conflictos (deberían ser solo
  aditivos, por la regla 6).
- **Santa Lucía intacta:** su suite sigue en ≥98%, el `terraform plan` del stack completo no
  muestra cambios en los recursos de Santa Lucía, y CI está en verde.
- README con una sección de Uruguay y la decisión de privacidad (Ley 18.331, sin conclusión
  legal). Actualizar el diagrama.
- `roadmap.md`: **una** fila nueva en su tracker que apunta a este archivo. Ojo con la trampa del
  conflicto aditivo en `roadmap.md` (ver la memoria del workflow): ante un conflicto se conservan
  los dos lados.
- El PR se abre hacia `master`. Desde ahí, los PRs de Uruguay salen de `master` como cualquier
  otro.

---

# Después de v1 (diferido)

| ID | Tema | Notas |
|---|---|---|
| UL1 | Lotería Uruguaya | Un adaptador más y una fila en `game_rules`. La frecuencia se confirma en UY-006. |
| UL2 | Kini (histórico; en el sitio, de 2006-08-15 a 2013-12-27) | Solo backfill, sin peticiones nuevas: los datos ya están en el bronce de `ver_resultados` (UY-006). No necesita incremental. |
| UL3 | "4 de la Suerte" | Primero averiguar si llegó a lanzarse. |
| UL4 | Otros países (Argentina, Brasil, Chile) | Es la prueba real del núcleo agnóstico de UY-010. Si agregar un país obliga a tocar el núcleo, el diseño falló. |
| UL5 | Pozos en términos reales (ajustados por inflación) | Necesita la serie del IPC de Uruguay (INE). |

---

# Tracker

Estados: `todo`, `in-progress`, `merged`, `blocked`, `dropped`. Las fases avanzan por gates
(G1 a G4), no solo por número.

| PR | Título | Estado | Link |
|---|---|---|---|
| UY-000 | Higiene de la rama beta (push, mover el brief, `.gitignore`) | merged | [#83](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/83) |
| *Fase 1 — Exploración* | | | |
| UY-001 | Cliente HTTP cortés y guard `DET_INVALIDAS`, **más el scraper de bronce completo** (adelantado) | merged (commit directo `ad6bf1f`, sin PR; publicado con la rama el 2026-10-05) · backfill completo **terminado** el 2026-10-04: 7.370 días de `resultados` (6.908 `draw`, 457 `no_draw`, 1 `not_yet_published` = 2026-10-04, 4 `error` = 2019-09-25/26/27/30 «game blocks without extract codes», explicados en UY-002: un paro de AFAL) | — |
| UY-002 | Sondeo de `ver_resultados` (Q1, Q2, Q3, Q7) | **merged**: Q1 **verificada** en FINDINGS.md (2.072 sorteos; `ver_resultados` y el extracto coinciden en el 100% de los valores; sin número de sorteo; 12,6% fuera de mié./dom.; los 5 números se publican ordenados) · Q2, Q3 (parte `ver_resultados`) y Q7 **escritas** en FINDINGS.md: día sin sorteo = HTTP 200 sin bloques; Quiniela V+N lun.–vie., solo N el sábado, nunca el domingo (sin cambios desde 2006, la bisección no hizo falta); los 4 `error` de 2019 son un paro de AFAL (con fuente de prensa); inicio 2006-08-11; Kini hasta 2013-12-27; códigos de Lotería 27–38 sin mapear (va a UY-006); todo UTF-8 · Fixtures: los de UY-001 ya cubren los casos; falta una página `error` (1 petición) | [#84](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/84), [#93](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/93) |
| UY-003 | Sondeo de `extractosweb` y PDF (Q3, Q5, Q7) | **merged**: Q3, Q5 y Q7 **escritas** en FINDINGS.md: el PDF es una impresión del extracto PHP desde el navegador y coincide en el 100% de los campos (243 PDF, 2018–2026) → **decisión del owner:** plata sale del HTML; el PDF se baja como respaldo solo si UY-005 confirma que no hace falta proxy; el PDF tiene 2 huecos y 2 imágenes sin texto, el PHP ninguno; los PDF de oct. 2018 son pruebas; pdfplumber > pypdf; el PDF de pozos trae el número de sorteo · **bug:** `classify.py` marca como `error` la plantilla vacía de la Quiniela (`extracto_sin_info.gif`), arreglo en un PR aparte · `not_yet_published` medido el 2026-10-14: el HTML sale entre 3 y 13 min después del sorteo y el PDF a los 10–14 min | [#94](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/94) |
| UY-003.1 | Fix: la plantilla vacía de la Quiniela (`extracto_sin_info.gif`) ya no es `error` | merged: `classify.py` la trata como vacía, con 2 fixtures reales y su test (que falla sin el arreglo); `CLASSIFIER_VERSION` = 2026-10-14 | [#96](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/96) |
| UY-004 | Metadatos, reglas, términos y estadísticas (Q8, Q9, Q10) | **merged** (junto con UY-005): Q8, Q9 y Q10 **escritas** en FINDINGS.md · **rango del 5 de Oro: 01–44 hasta 2014-03-16 y 01–48 desde 2014-03-19 (As. 176/2014)**, corrige Q1 · 8 resoluciones escaneadas leídas → `docs/uruguay/drafts/game_rules_5_de_oro.csv` (29 filas con URL) · `noticias.php` → `docs/uruguay/drafts/calendar_events.csv` (54 eventos, todos coinciden con el manifiesto; 5 de 2014–2015 sin URL) · paro de 2019 confirmado por los OIS 2036 y 2037 · `ver_estadisticas` coincide con el bronce salvo una Revancha mal fechada (2010-10-07 = 2010-11-07) · sin términos de uso ni aviso legal · `ver_resultados_pdf.php` mapea 75 códigos de Lotería (va a UY-006) | [#95](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/95) |
| UY-005 | Acceso al sitio desde AWS (CloudShell) | **merged** (junto con UY-004): **verificado el 2026-10-15 desde us-east-1, sin proxy** (nginx sin CDN ni WAF; el PDF llega idéntico, mismo SHA-256) → en la nube se bajan HTML y PDF (regla del owner en UY-003) | [#95](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/95) |
| UY-006 | (Secundario) Lotería Uruguaya y Kini (Q4, Q6) | **merged**: Q4 y Q6 **escritas** en FINDINGS.md · Lotería: el PDF `{aaaammdd}l.pdf` desde 2018-11-30 para cualquier código; los PHP de Lotería leen por fecha (el corrimiento de los códigos 35–38 es cosmético) · frecuencia: viernes, ~42 al año hasta 2012 y 12 al año desde 2014 · Kini: lun.–vie., 2006-08-15 a 2013-12-27, 5 números 01–36, ya en bronce; **sigue diferido (UL2), decisión del owner** | [#97](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/97) |
| UY-007 | Cierre de FINDINGS.md → **G1** | **merged**, **G1 aprobado** por el owner (2026-10-16): FINDINGS.md abre con el cierre (decisiones del owner, lo que se decide en UY-010/011, huecos, contradicciones C8–C15) · **C7 decidida:** cupones solo en bronce · Decreto 635/989 leído en IMPO: el 5 de Oro nació con 01–36 y el cambio a 01–44 queda como hueco que no bloquea G1 · fixture `error` real (2019-09-25, 1 petición) con su test · C13–C15 nuevas | [#100](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/100) |
| *Fase 2 — Diseño* | | | |
| UY-010 | Esquema canónico, paquete, runtime, YAML y épocas | **merged** (2026-10-18): `docs/uruguay/DESIGN.md` escrito · **decisiones del owner D1–D7 aprobadas el 2026-10-16:** `src/sorteos/core/` + `src/sorteos/<iso2>/` con `country`/`operator`/`game` en plata; **Lambda 3.12, Glue Python Shell descartado** (C6); `draw_numbers` largo, clave de la Quiniela = (sorteo, posición); un YAML por juego (configuración, no dato); una época de parser por fuente; montos por fuente en `decimal(18,2)`, vacío = nulo, `currency`; **C7: plata guarda cuántos cupones ganaron** · verificado sobre el bronce: los 3 extractos tienen una sola plantilla 2006–2026 y `ver_resultados` solo cambia por el Kini (2013) y unos botones (2016-05-29) → UY-022/023 se juntan; Quiniela en orden de extracción con repetidos en el 17,5% e igual en las dos fuentes en los 10.877 sorteos; la Tómbola = terminaciones distintas de la Quiniela + reposiciones (10.846/10.877, excepciones solo en 2006) · propuestas P1–P7 esperan G2 | [#101](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/101) |
| UY-011 | Manifiesto, backfill/incremental, pruebas y riesgos → **G2** | **merged** (2026-10-25), **G2 aprobado** por el owner: DESIGN.md completo con D8–D23 y P8–P14 (el detalle de lo medido está en #111) · la Fase 3 se reescribió en el PR siguiente | [#111](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/111) |
| UY-011.1 | Fix: cupones falsos en los fixtures (C7) | **merged** (2026-10-23, #102): `scripts/uy_redact_fixture.py` reemplaza cada cupón por uno falso con la misma forma (`000000001-0`, numerado por página); los 5 cupones reales de 2 fixtures se reemplazaron; el scanner de privacidad falla ante un cupón que no empiece con `000000`. Los reales siguen en la historia de git (el owner lo aceptó: no se reescribe una rama protegida) | [#102](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/102) |
| *Fase 3 — Construcción local* | | | |
| UY-020 | Esqueleto, YAML, registro y migración de `loteria_uy` | **merged** (2026-10-27): `src/loteria_uy/` → `src/sorteos/{core,uy}/` con `git mv` · `core/` ya no sabe de Uruguay: el cliente HTTP exige `blocklist` (sin valor por defecto) y `agent`, el bronce exige `country` · `DET_INVALIDAS` en `uy/privacy.py`, en código (P5) · `core/config.py`: cargador estricto (claves duplicadas, desconocidas o faltantes, textos sin comillas, referencias cruzadas, épocas sin huecos) · `site.yaml` + 3 YAML de juegos con las URLs como plantillas; `other_games` con los códigos fuera de v1 · los 2 CSV a `uy/reference/` (mismos bytes) · extra `uy` · **test de oro: las 20.612 URLs del manifiesto salen idénticas de los YAML** (`make uy-golden-urls`; las 1.060 de pozos son links) y una muestra de 43 filas en CI · el criterio decía "53 tests" pero eran 102; hoy son 255, `sorteos` al 100% · `uy-report` idéntico al de antes · arreglo de paso: un test de UY dejaba el logger raíz en INFO y rompía uno de CloudWatch cuando la mudanza cambió el orden de pytest | [#129](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/129) |
| UY-021 | Manifiesto como interfaz, 3 fallas y `manual_overrides` | **merged** (2026-10-28): `core/manifest.py` nuevo, `bronze.py` queda solo con el almacén · `Manifest` es un `Protocol` (`get`, `record`, `effective_state`, `history`, `summary`, `date_range`) y `SqliteManifest` su backend, **sin cambiar el esquema** (un test congela el de UY-001) · **3 fallas iguales → `missing`** por firma (`http_status`, `content_sha256`) o `detail` sin respuesta; `fetch_log` guarda el `error` que vio y solo la fila del manifiesto guarda la decisión (owner, 1a) · `manual_overrides.csv` con los 4 días del paro → `no_draw`, solo `no_draw`/`missing` (owner, 2a), cargador estricto contra `calendar_events` · el backfill salta por estado efectivo y el reporte lista las correcciones · **hallazgo:** las páginas del paro cambian de hash en cada pedido, así que la regla nunca las cerraría y solo `manual_overrides` lo hace · **corrida en seco sobre una copia del manifiesto real, cero peticiones:** los 35 pozos pasan a `missing` tras dos respuestas iguales simuladas y un backfill 2006-08-01..2026-10-20 (`resultados,extractos,pozos`) pide 0 y salta 21.425 · 815 tests, `sorteos` al 100% | [#130](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/130) |
| UY-022 | Un solo parser de `ver_resultados` (2006–2026) | **merged** (2026-10-28): `uy/parsers/resultados.py`, función pura bytes + fecha → `ParsedDraw` por juego (números con sus ceros, posición de la Quiniela tomada de su imagen `l_NN`, premios del 5 de Oro con monto, estado y **cantidad** de cupones) · `PageError` (todo el día a cuarentena) frente a `FailedDraw` (solo ese sorteo) · el bloque "de hoy" se excluye por estructura · Lotería y Kini se reconocen y se saltan · `core/money.py` (los dos estilos de D6, owner 1a) y `core/dates.py` (regla 6 de D14) · sin `dq_flags`: los deriva UY-025 (owner 2a) · **arreglo:** los códigos 27–38 son Lotería (UY-006) y faltaban en `site.yaml`; sin ellos 15 días iban enteros a cuarentena · **decisiones del owner:** la Vespertina del 2006-08-31 sin Tómbola entra sin filas de Tómbola; el "Próximo" con fecha larga se lee; las grafías de "Sin Aciertos" y "Vacante" son `no_winners` · **corrige FINDINGS:** las 25 celdas vacías de Q1 son 11 · **propiedades sobre los 6.924 `resultados` del bronce, sin peticiones:** 12.979 sorteos (5.948 N, 4.954 V, 2.077 5 de Oro), 0 a cuarentena, 436 días con Lotería, Quiniela con repetidos 17,5 %, Tómbola con repetidos 31 (todas de 2006), 2 `next_draw_unparsed` · 6 fixtures nuevos · parser, money y dates al 100% con ramas | [#131](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/131) |
| UY-023 | Parsers de los extractos PHP | **merged** (2026-10-28): `uy/parsers/extracto_quiniela.py` (números por su imagen `p_N`, y `started_local`/`first_ball_local`/`ended_local` como hora de Montevideo sin zona; `hrs.` vacío = nulo) y `extracto_5_de_oro.py` (11 números, pozos en estilo `uy` con `0,00` = nulo, ganadores **por celda del DOM** para que una celda vacía no se corra) · `parsers/common.py` con lo compartido (UY-022 se refactorizó sin cambiar resultados) · **`cross_check.compare()`** (owner 1a): diferencias campo por campo (números, "Próximo", monto, ganadores) · **flag nuevo `timing_out_of_order`** en el catálogo de DESIGN (owner 2a): la Nocturna 2009-08-01 termina a las 15:24 tras empezar a las 21:00, se guarda como se publicó · los nombres de los funcionarios no se leen · **propiedades sobre el bronce, sin peticiones:** 12.979 extractos (4.954 V, 5.948 N, 2.077 5 de Oro), 0 fallas, y **`compare()` contra `ver_resultados`: 0 diferencias en los 12.979 pares** · ningún sorteo cruza la medianoche (último fin 22:24) · 4 fixtures nuevos · los 6 módulos de `parsers/` al 100% con ramas | [#132](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/132) |
| UY-024 | PDF de pozos y su formato en `core/money.py` | **merged** (2026-10-28): `uy/parsers/pozos_pdf.py` con pdfplumber: fecha, `draw_number`, hora de emisión y los 3 pozos anunciados, contra una regex estricta de las 7 líneas del reporte · **los montos están en estilo `uy`, así que `money.py` no necesitó un formato nuevo** (corrige D6) · el YAML declara `money_style` y la época del PDF (desde 2016-06-01) · **flag nuevo `draw_number_out_of_sequence`** (owner, a): la racha de 2017 (07-30 = 1967 en vez de 1966; 08-16 repite el 1971) se guarda como se publicó y GX exige la unicidad sin esas filas · **propiedades sobre el bronce, sin peticiones:** 1.025 PDF, 0 fallas, número 1847..2920 consecutivo en 1.072 de 1.074 sorteos, 49 sin número (35 `error` + 14 días sin enlace; DESIGN decía 35), pozos iguales a `ver_resultados` en 3.071 de 3.075 (4 por centavos) · 2 PDF como fixtures (2016 y 2026) · `pozos_pdf.py` al 100% con ramas · `pdfplumber` no estaba en el `.venv` local (el CI ya lo instala por el extra `dev`) | [#133](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/133) |
| UY-025 | Plata, validaciones cruzadas y cuarentena | **merged** (2026-10-28), en tres PRs (owner, 1a): **UY-025.1** `core/silver.py` (esquemas, catálogo cerrado de flags, linaje, reescritura por año, tablas de referencia) · **UY-025.2** el transform de UY (parsers → filas, cuarentena, `cross_source_check`, P7, los 7 flags de un sorteo) · **UY-025.3** la serie del número de sorteo y la corrida completa · **decisiones del owner:** una fuente secundaria que existe pero no parsea manda el sorteo entero a cuarentena (2a); el linaje apunta a `ver_resultados` y `parser_version` lista cada fuente que aportó (3a) · **UY-025.1 merged** ([#134](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/134)): catálogo en `uy/dq_flags.py`, columnas de partición solo en la ruta, y los CSV de referencia con fechas tipadas (`2009-02` → nulo; el paro de 2019-09-25/26 partido en dos filas por día, owner 1a) · **UY-025.2 merged** ([#135](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/135)): `uy/silver.py` (bronce → filas por año) y `core/shapes.py` (rango de `game_rules`, repetidos, `not_in`, orden → cuarentena) · **propiedades sobre todo el bronce, sin peticiones:** 12.979 sorteos, 458.907 números, 6.231 premios, **0 a cuarentena**, los 12.979 `match` con su extracto · flags iguales al catálogo: 17 `next_draw_implausible`, 2 `next_draw_unparsed`, 1 `pozo_plata_equals_oro`, 1 `timing_out_of_order`, 31 `tombola_repeated_number` = los mismos 31 `tombola_not_from_quiniela` (DESIGN decía 30 a 31) · reposiciones de la Tómbola: 1,787 de media (el azar da ≈ 1,8) · toda la historia en ~255 s (≈ 12 s por año), 5,1 MB de plata · **UY-025.3 merged** ([#136](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/136)): `number_series()` arma la serie del número de sorteo una vez por corrida, a través de los años, desde los `games` del manifiesto; un PDF en `draw` que no parsea manda el sorteo a cuarentena (2a) · **corrida final sobre todo el bronce:** los 9 flags exactos del catálogo (49 `draw_number_inferred`, 2 `draw_number_out_of_sequence`, 17, 2, 1, 1, 31, 31, 0 `amount_sources_differ`), 0 a cuarentena, los 1.074 sorteos del 5 de Oro desde 2016-06-01 con número (1847..2920) y ninguno antes, número único sin las 2 filas fuera de secuencia, los 49 inferidos iguales contados hacia adelante o hacia atrás, ~280 s | [#134](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/134), [#135](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/135), [#136](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/136) |
| UY-026 | Suites de GX para UY | **merged** (2026-10-29), en dos PRs (owner, 1a): **UY-026.1** las suites, su JSON y el runner local · **UY-026.2** GX empaquetado como wheels · el job de Glue y la medición del arranque pasan a la Fase 5 · **UY-026.1 merged:** 5 suites (las 13 expectativas de DESIGN más filas y linaje, owner 3a; lo que es de un sorteo, medido en pandas y validado por GX, owner 2a) en verde sobre toda la plata local en ~34 s; la Tómbola queda en 20 números o ninguno por la Vespertina del 2006-08-31 (UY-022) · **UY-026.2 merged** (2026-10-29): `dist/uy/uy_dq.gluewheels.zip` (owner 1a), solo con lo que Glue 5.0 no trae (owner 2a): 25 wheels, ~49 MB, con `sorteos` como wheel adentro porque `core/config.py` lee archivos con `open()`; lock para Python 3.11 resuelto con `pip --dry-run --report`; el CI (owner 3a) instala el zip con `--no-index` sobre `pandas` 2.2.2, `numpy` 1.26.4 y `pyarrow` 17 y corre ahí los tests del gate | [#137](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/137), [#138](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/138) |
| UY-027 | CLI y targets de Make | **merged** (2026-10-31), en dos PRs (owner, 1a): **UY-027.1** el incremental y `uy-silver` (owner, 2a), con una corrida real antes de entrar (owner, 4a); `draw_gaps` se le suma en UY-028 (owner, 3a) · **UY-027.2** `uy-properties`, que falla solo ante parseos fallidos o cuarentena (owner, 5a) · **UY-027.1 merged** (2026-10-31; el CI pidió un arreglo de bandit B608 en `open_keys()`, ahora con una consulta fija): `make uy-incremental` (7 días, o desde el día siguiente al último sorteo, más las claves abiertas, con las cuatro fuentes y después la plata de los años tocados) y `make uy-silver` · **3 corridas reales:** #1 (10-29 12:33, 79 peticiones) y #2 (16:22, 38) cierran los 35 pozos como `missing` y dejan `open_keys()` vacío; #2 encontró que una página pedida a media tarde queda en `draw` solo con la Vespertina → una página de resultados con menos de 3 días se vuelve a pedir (`6ccf5c47`); #3 (10-31 15:13, 9 peticiones) lo confirma: aparece la Nocturna del 10-29 con su extracto y su PDF · `uy-dq` en verde sobre 12.999 sorteos, 0 en cuarentena · **UY-027.2 merged** (2026-10-31; en la revisión salió una constante sin uso, `TOMBOLA_SIZE`): `make uy-properties` corre la plata de todos los años en memoria (sin escribir ni pedir) y sale con 1 solo ante cuarentena; los años salen de `build_silver.all_years()` · sobre todo el bronce: 12.999 sorteos, 0 a cuarentena, los 12.999 `match`, los 9 flags del catálogo iguales a UY-025.3, ~4 min | [#139](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/139), [#140](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/140) |
| UY-028 | Detector de huecos (`expected_draws()` y `draw_gaps`) | **merged** (2026-11-01), en dos PRs (owner, 1a): **UY-028.1** `expected_draws()` en `core/gaps.py`, pura, con tablas de casos y la medición sobre la plata real · **UY-028.2** la tabla `draw_gaps`, un solo archivo por país recalculado entero en cada corrida (owner, 2a), en `uy-silver` y `uy-incremental`, con su expectativa de GX · un día en cuarentena no se trata aparte: la cuarentena ya frena la corrida antes del detector (owner, 3a) · **UY-028.1 merged** (2026-10-31): un par es acierto, adelanto o hueco; el tope de P10 vive en `gaps.believed()` y el flag `next_draw_implausible` lo usa · **corrige DESIGN:** el 2006-08-27 no es un hueco, porque el 2006-08-23 anunció el 2006-09-03 (la fecha larga que se lee desde UY-022) · con los cortes de DESIGN: 5 de Oro 2.073 aciertos (99,86 %), 1 adelanto y 2 huecos; Vespertina y Nocturna exactamente 99,98 % y 99,97 % · **los 4 huecos de la historia explicados y ninguno abierto** · **UY-028.2 merged** (2026-11-01): `draw_gaps` en plata (un archivo por país, linaje del sorteo cuya expectativa falló) desde `uy-silver` y desde cada incremental, aunque no cambie nada; con cuarentena en plata no se reescribe y la corrida sale con 1; sexta suite `uy_draw_gaps`; el conteo en `uy-properties` · **arreglo de UY-028.1:** un hueco en curso solo se explica con un evento dentro de su ventana (antes, cualquiera hasta hoy) · sobre todo el bronce: 4 huecos `explained`, 0 abiertos, 6 suites en verde | [#141](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/141), [#142](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/142) |
| *Fase 4 — Pruebas locales* | | | |
| UY-030 | Reconciliación de toda la historia (con UY-031) | **en curso** (2026-11-01), en dos PRs (owner, 5a) · **UY-030.1 merged** (2026-11-01): `core/reconcile.py` explica cada día hábil del calendario de cada juego desde las mismas expectativas que `draw_gaps` (salteado por un anuncio, corrido dentro de la ventana, o hueco) y cada sorteo fuera del calendario (anunciado, corrido u otro); `make uy-reconcile` lo cruza con los días hábiles contados desde las fechas, recalcula `draw_gaps`, revisa el número de sorteo y la cuarentena, y sale con 1 ante cualquier diferencia · **sobre toda la plata:** los 13.713 días hábiles del calendario explicados (911 salteados por anuncio, casi todos feriados; 65 corridos; 13 en los 4 huecos explicados; 0 abiertos), 275 sorteos del 5 de Oro fuera del calendario (246 anunciados, 28 corridos, 1 después del paro de 2019) · número de sorteo 1847..2923 en 1.077 sorteos, 1.074 pasos de +1 y las 2 rupturas de 2017 con su flag · 0 en cuarentena · **D18 medido:** el año más lento es 2011 con 14,9 s y 2016 tarda 12,7 s (toda la historia en ~281 s, con la serie del número), lejos de los 900 s de una Lambda · **UY-030.2 en revisión:** `post()` en el cliente cortés (los mismos reintentos, guard y 1 req/s; tras un 301/302/303 sigue con GET), `make uy-estadisticas` (12 POST con los valores que ofrece el formulario, guardados en bronce con su `queries.json`) y la sección `ver_estadisticas` de `uy-reconcile` (sin peticiones, desde el último juego en bronce; una diferencia sin explicar hace fallar) · **hallazgo:** el formulario de Quiniela es solo la Vespertina, y la Nocturna no tiene uno (owner, 7a) · **las 12 coinciden con toda la plata:** 5 de Oro y Revancha 2006–2026 (4.161 consultados, 20.805 apariciones), la Vespertina 2007–2026 en las 9 posiciones sueltas y la 1–20 (97.380) y la Tómbola (97.380); la única diferencia es la Revancha del 2010-10-07, explicada (owner, 9a) · 18 peticiones en total (4 GET y 2 POST de sondeo, y las 12) | [#143](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/143) |
| ~~UY-031~~ | Se juntó con UY-030 (owner, 2026-11-01) | — | — |
| UY-032 | Oro local: auditoría de aleatoriedad | todo | — |
| UY-033 | Incremental en local durante 2 semanas → **G3** | todo | — |
| *Fase 5 — Nube* | | | |
| UY-040 | Decisiones de la nube | todo | — |
| UY-041 | Almacenamiento, IAM y LF | todo | — |
| UY-042 | Subir el bronce y reconciliar | todo | — |
| UY-043 | Orquestación incremental | todo | — |
| UY-044 | Oro en Athena (atómico) | todo | — |
| UY-045 | Alarmas y canario → **G4** | todo | — |
| *Fase 6 — Merge* | | | |
| UY-050 | `loteria-uruguaya-test` → `master` | todo | — |
