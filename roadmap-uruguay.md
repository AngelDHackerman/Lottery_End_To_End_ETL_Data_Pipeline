# Roadmap — Loterías de Uruguay (extensión del proyecto, beta)
**Owner:** Angel Hernandez
**Brief de origen:** [`docs/uruguay/BRIEF.md`](./docs/uruguay/BRIEF.md)
**Rama base:** `loteria-uruguaya-test` (hace de `master` para esta extensión hasta la fase de merge)
**Última actualización:** 2026-10-06

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
> **Fuera de v1:** Lotería Uruguaya, Kini (descontinuado en 2014), "4 de la Suerte" y otros países.

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
| C5 | Los horarios "Inicio/Fin/Primero" de la Quiniela | Uruguay eliminó el horario de verano en 2015. Antes de esa fecha la hora local tenía dos offsets. | `draw_timing` guarda la hora local más la zona `America/Montevideo` (el offset se deriva) y nunca un offset fijo de -03:00. |
| C6 | Código destinado a Glue | Glue Python Shell llega como máximo a 3.9 (PR-020, PR-050). Si el parser de UY corre ahí, ruff no debe "modernizarlo". | Decidir el runtime de destino en UY-010, **antes** de escribir los parsers. Si es Glue 3.9, ampliar el guard de PR-050 al paquete nuevo. |
| C7 | Los fixtures del brief incluyen números de cupón (`#########-#`) | No identifican a una persona, pero el brief exige preguntar cualquier decisión nueva sobre datos personales. | Pregunta para el owner en UY-007: ¿los cupones ganadores entran en plata o se quedan solo en bronce? |
| C8 | "El sorteo más antiguo… 07/01/2007" y el selector del sitio (2007–2026) | **Verificado 2026-10-04:** `ver_resultados.php` acepta 2006, y el primer día con datos es el **11/08/2006** (Lotería + Quiniela Nocturna), hallado por bisección. Antes de esa fecha la página sale vacía. | El backfill arranca el 2006-08-01, y el manifiesto deja registrado dónde empieza la historia. |
| C9 | "Después de ~2010 algunas URLs descargan un PDF" | **Verificado:** el `MostrarExtracto()` del sitio cambia al PDF estático `/extractosweb/{aaaammdd}{o\|v\|n\|l}.pdf` desde el **30/11/2018**, no en 2010. Ese PDF responde 404 cuando no hubo sorteo, y el extracto PHP sigue respondiendo para todas las fechas. | Las dos son fuentes de bronce separadas (`extractos` y `pdf`). |
| C10 | 5 de Oro "miércoles y domingo" | **Verificado:** 261 de 2.072 sorteos (12,6%) caen otro día, sobre todo jueves (186) y lunes (75), por feriados, paros o fútbol (informado por el owner). | El sorteo esperado es el "Próximo sorteo" que anunció el anterior (acierta en el 98,3%), con una tolerancia de +3 días. Ver FINDINGS.md. |
| C11 | El número de sorteo como clave natural y detector de huecos | **Verificado:** no se publica ni en `ver_resultados` ni en el extracto. Solo está en el PDF de pozos (desde ~2016). | La clave es la fecha y el juego. Los huecos se detectan con "Próximo sorteo" y `calendar_events`. |
| C12 | Montos en estilo EE.UU. "en el HTML de 2016" | **Verificado:** `ver_resultados` usa estilo EE.UU. desde 2006 y el extracto usa estilo uruguayo en todas las épocas. | Un parser de montos por fuente, no por época. |

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

**Aceptación:** el resultado queda en FINDINGS.md como verificado.

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

El detalle de cada PR se escribe al cerrar G2, porque depende del diseño aprobado. El orden y el
alcance son estos:

| PR | Qué | Notas |
|---|---|---|
| UY-020 | Esqueleto del paquete, carga del YAML y registro de juegos | Mueve el cliente de UY-001 a su lugar definitivo. Dependencias nuevas (pyyaml y la biblioteca de PDF) en un extra propio en `pyproject.toml`. |
| UY-021 | Manifiesto y almacén de bronce local | Rutas idénticas a las futuras claves de S3 (`country=uy/game=…/draw_date=…`), para que la Fase 5 solo cambie el backend. |
| UY-022 | Parser de `ver_resultados`, layout 2007 → 2016-06 | Quiniela, Tómbola y 5 de Oro (si Q1 lo confirma). Ignora el bloque "Sorteos para el día de hoy". |
| UY-023 | Parser de `ver_resultados`, layout desde 2016-07 | Posiciones numeradas y montos en estilo EE.UU. |
| UY-024 | Parsers de extractos (HTML, y PDF si Q5 lo exige) | Distingue "Vacío" de "Sin Aciertos". Cupones según la decisión C7. |
| UY-025 | Escritor de plata (Parquet) con validaciones cruzadas y cuarentena | Las validaciones: "Próximo sorteo", continuidad del número de sorteo, Tómbola ⊇ las dos últimas cifras de la Quiniela, `is_replacement`. Las filas rechazadas van a `quarantine/`, como en PR-044. Cuidado con el tipo Parquet `Null` en columnas que vienen todas en None (ver la memoria sobre tipos de Parquet). |
| UY-026 | Suites de GX para la plata de UY | Las expectativas se derivan de los datos, no se inventan (la lección de PR-032). |
| UY-027 | CLI y targets de Make: `uy-backfill --from --to`, `uy-incremental` y `uy-report` | Todos se pueden reanudar. |

---

# Fase 4 — Pruebas en local (backfill y análisis)

| PR | Qué | Criterio |
|---|---|---|
| UY-030 | **Backfill piloto de un año** (2016, porque cruza el cambio de layout) | Conteos por juego y mes contra el calendario esperado. Cada hueco queda explicado por `calendar_events` o sigue abierto. Se corrigen los parsers. |
| UY-031 | **Backfill completo** de 2007 a hoy | La capa 1 tarda unas 2 h y la capa 2 lo que haga falta. Reporte de reconciliación: continuidad del número de sorteo, comparación con `ver_estadisticas`, tasa de cuarentena. |
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
| UL2 | Kini (histórico, 2007–2014) | Solo backfill. No necesita incremental. |
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
| UY-001 | Cliente HTTP cortés y guard `DET_INVALIDAS`, **más el scraper de bronce completo** (adelantado) | merged (commit directo `ad6bf1f`, sin PR; publicado con la rama el 2026-10-05) · backfill completo **terminado** el 2026-10-04: 7.370 días de `resultados` (6.908 `draw`, 457 `no_draw`, 1 `not_yet_published` = 2026-10-04, 4 `error` = 2019-09-25/26/27/30 «game blocks without extract codes», pendiente para UY-002) | — |
| UY-002 | Sondeo de `ver_resultados` (Q1, Q2, Q3, Q7) | **en curso**: Q1 **verificada** y escrita en FINDINGS.md (2.072 sorteos, mismos campos que el extracto, sin número de sorteo, 12,6% fuera de mié./dom.); falta la comparación valor por valor · Q2, Q3 (inicio 2006-08-11) y Q7 respondidas, falta escribirlas | — |
| UY-003 | Sondeo de `extractosweb` y PDF (Q3, Q5, Q7) | **en curso**: Q5 respondida (PDF desde 2018-11-30, 404 si no hubo, sin `Content-Disposition`); falta comparar HTML con PDF | — |
| UY-004 | Metadatos, reglas, términos y estadísticas (Q8, Q9, Q10) | todo | — |
| UY-005 | Acceso al sitio desde AWS (CloudShell) | todo | — |
| UY-006 | (Secundario) Lotería Uruguaya y Kini (Q4, Q6) | Q4 **respondida** (rutas en `MostrarExtracto()`) · Q6 todo | — |
| UY-007 | Cierre de FINDINGS.md → **G1** | todo | — |
| *Fase 2 — Diseño* | | | |
| UY-010 | Esquema canónico, paquete, runtime, YAML y épocas | todo | — |
| UY-011 | Manifiesto, backfill/incremental, pruebas y riesgos → **G2** | todo | — |
| *Fase 3 — Construcción local* | | | |
| UY-020 | Esqueleto, YAML y registro | todo | — |
| UY-021 | Manifiesto y bronce local | todo | — |
| UY-022 | Parser `ver_resultados` 2007 → 2016-06 | todo | — |
| UY-023 | Parser `ver_resultados` desde 2016-07 | todo | — |
| UY-024 | Parsers de extractos (HTML y PDF) | todo | — |
| UY-025 | Plata, validaciones cruzadas y cuarentena | todo | — |
| UY-026 | Suites de GX para UY | todo | — |
| UY-027 | CLI y targets de Make | todo | — |
| *Fase 4 — Pruebas locales* | | | |
| UY-030 | Backfill piloto (2016) | todo | — |
| UY-031 | Backfill completo y reconciliación | todo | — |
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
