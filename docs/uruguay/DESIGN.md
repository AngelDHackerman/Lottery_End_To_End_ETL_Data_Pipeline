# DESIGN — Diseño de la extensión a Uruguay (UY-010)

Entregable de UY-010 en [`roadmap-uruguay.md`](../../roadmap-uruguay.md). Parte de lo verificado en
[`FINDINGS.md`](FINDINGS.md) (gate G1, aprobado el 2026-10-16). UY-011 le suma la ingesta, las
pruebas y los riesgos, y el documento completo es lo que el owner aprueba en el gate **G2**. Usa las
mismas etiquetas que FINDINGS: **verificado**, **observado**, **hipótesis** e **informado por el
owner**.

**Cómo leerlo.** Las [decisiones D1–D23](#decisiones-del-owner-2026-10-16) ya están aprobadas. Las
[propuestas P1–P14](#propuestas-de-este-documento-se-aprueban-en-g2) salieron al escribir el detalle
y esperan un sí o un no en G2. El resto del documento explica cómo se aplican unas y otras.

---

## Decisiones del owner (2026-10-16)

| # | Tema | Decisión | Por qué |
|---|---|---|---|
| D1 | **Paquete y país en la ruta** | `src/sorteos/core/` (núcleo sin país) más `src/sorteos/<país>/`, con el código **ISO 3166-1 alfa-2 en minúscula** (`uy`, más adelante `gt`, `ar`). En plata, cada juego se identifica con `country` + `operator` + `game` (por ejemplo `uy` / `dnlq` / `quiniela_nocturna`). | Hay juegos con el mismo nombre en distintos países, y el país solo no alcanza: en Argentina cada provincia tiene su propia lotería y casi todas tienen una "Quiniela". Los códigos ISO no tienen tildes ni dependen del idioma, y el bronce ya usa `country=uy`. `src/loteria/` (Santa Lucía) no se toca hasta UY-050. |
| D2 | **Runtime de destino (C6)** | **Lambda con Python 3.12** para el extractor y el transform. El backfill de plata se parsea en local o con un `Map` de Step Functions por año. **Glue Python Shell queda descartado.** | Python Shell no pasa de 3.9, que llegó a fin de vida en octubre de 2025, y ataría todo `sorteos/core/` a esa versión. El costo no decide: los dos salen por centavos al año. Una corrida diaria son 3 o 4 páginas (segundos). Los 15 minutos de Lambda solo importan en el backfill (~20.000 HTML, ~0,9 GB), y por eso se reparte. El DQ con GX puede seguir en Glue Spark como en PR-050 (lo decide UY-011). |
| D3 | **Orden de los números** | Formato largo `draw_numbers` con `position`, `ball_type` y el número **como texto con sus ceros** (`'043'`). Cada juego declara si el orden es real o viene ordenado (`order: drawn` o `sorted`). En la Quiniela la clave es **(sorteo, posición)**, no (sorteo, número). | La Quiniela publica sus 20 números en el orden de extracción, y la posición es lo que se apuesta (el 1.º es "la cabeza"). El mismo número puede repetirse dentro de un sorteo. La Tómbola y el 5 de Oro se publican ordenados: son conjuntos y no admiten análisis por posición. Ver [Evidencia](#evidencia-verificada-el-2026-10-16). |
| D4 | **Un YAML por juego** | Un archivo de configuración por juego dentro del paquete (`src/sorteos/uy/games/*.yaml`), cargado con `yaml.safe_load` y validado contra un esquema estricto que falla al arrancar. Las reglas con vigencia **no** van en el YAML: siguen en `game_rules` y el YAML solo las referencia. | Separa lo que cambia entre juegos (URLs, calendario, forma de los números, épocas, fuentes) del código que parsea. Sumar un juego o un país es sumar un archivo. El YAML no es un dato: no va a bronce ni a plata (ver [Configuración](#configuración-los-yaml)). |
| D5 | **Épocas del parser** | El mecanismo existe (`parser_epochs` con `valid_from` y `valid_to` en el YAML), pero se arranca con **una sola época por fuente**. Si una página no tiene la forma esperada, va a cuarentena y el parser nunca adivina. Solo se agrega una época cuando un parseo real falla. Hay un fixture por cada variante conocida, y `parser_version` va en el linaje. | El HTML de Uruguay casi no cambió en 20 años (ver [Evidencia](#evidencia-verificada-el-2026-10-16)). Lo que cambió fueron las fuentes y las reglas: el PDF desde 2018, el de pozos desde 2016, el rango del 5 de Oro en 2014 y los datos tipeados a mano en 2006. |
| D6 | **Montos** | Un parser por **fuente** con una expresión regular estricta: `^\d{1,3}(,\d{3})*\.\d{2}$` para `ver_resultados` (estilo EE.UU.) y `^\d{1,3}(\.\d{3})*,\d{2}$` para el extracto (estilo uruguayo). Siempre `Decimal`, guardado como `decimal(18,2)` en Parquet y en el catálogo. El vacío (`$` sin monto o `0,00` de plantilla) pasa a **nulo, nunca a 0**. Lleva una columna `currency` (`'UYU'`). Plata guarda pesos nominales, y el ajuste por inflación va en oro. `ver_resultados` es la fuente principal, el extracto es el control, y si difieren queda un `dq_flag`. | Un monto como `365,323` o `1.234` es ambiguo si se lee sin saber de qué fuente vino. Lo que no encaja va a cuarentena. `currency` hace falta desde ya por D1 (Guatemala es `GTQ` y Argentina `ARS`). El PDF de pozos será un tercer formato, que se fija cuando se construya su parser (hoy hay solo 4 muestras verificadas). |
| D7 | **C7: cuántos cupones ganaron** | Plata guarda, por premio (Oro, Plata y Revancha), la **cantidad** de cupones ganadores, nunca sus números (que siguen solo en bronce). "Sin Aciertos" es `0` y la celda vacía es **nulo**. | Permite medir qué tan común es que un pozo se reparta entre varios o que un solo cupón se lo lleve entero, y calcular el premio por cupón. Es un conteo de **cupones**, no de personas: alguien con dos cupones ganadores cuenta dos veces, y eso se aclara en el diccionario de datos. |
| D8 | **Cinco estados en el manifiesto** | Se mantienen `draw`, `no_draw`, `not_yet_published`, `missing` y `error`. Son finales `draw`, `no_draw` y `missing`. Ver [Manifiesto](#manifiesto-uy-011). | `missing` separa un hueco de la fuente (el juego figura en `ver_resultados` pero su extracto no está) de un día sin sorteo. |
| D9 | **El manifiesto registra lo que mostró la página** | El *settle* sigue en 3 días fijos. Lo que se esperaba ese día lo decide el detector de huecos, que es otra pieza. | Mezclar las dos cosas haría que un error del calendario esperado cambie lo que se guardó. |
| D10 | **Correcciones manuales en una tabla aparte** | `manual_overrides`, donde cada fila cita una fila de `calendar_events`. El manifiesto no se edita a mano. | Así se conserva lo que clasificó el código y queda escrito quién corrigió qué, y por qué. |
| D11 | **Tres fallas iguales pasan a `missing`** | Un `error` que falla igual en 3 corridas seguidas pasa a `missing` (owner, 2026-10-21). | Sin esto, los 35 PDF de pozos con error se volverían a pedir en cada corrida diaria para siempre. |
| D12 | **El manifiesto es una interfaz** | Un `Protocol` desde UY-021, con SQLite como implementación local. DynamoDB es la candidata para la nube (UY-040). En la v1 nunca se vuelve a pedir una página final. | La Fase 5 cambia el backend sin tocar a quien lo usa. |
| D13 | **Un solo detector de huecos** | Una función pura, `expected_draws()`, que usan tanto el reporte del backfill como la alarma del incremental. Su salida es la tabla de plata `draw_gaps`. Ver [Detector de huecos](#detector-de-huecos-uy-011). | Si el reporte y la alarma tuvieran cada uno su lógica, tarde o temprano dirían cosas distintas sobre el mismo día. |
| D14 | **La regla combinada** (Q7, 2026-10-21) | Se espera la fecha que anunció el sorteo anterior si cae en (anterior, anterior + 14 días] (el tope pasó de 7 a 14 con P10, aprobada el 2026-10-25); si no, el siguiente día del calendario del juego. Hay hueco si no hay sorteo entre esa fecha y 3 días después. Un anuncio descartado lleva `next_draw_implausible`. Las fechas se leen aceptando cualquier separador, sin corregir nunca un dígito. | Ninguna de las dos fuentes alcanza sola. El anuncio acierta el 98 % y el calendario no ve feriados ni traslados; combinadas pasan del 99,7 %. |
| D15 | **Los huecos conocidos son filas de `calendar_events`** | Semana de Turismo, fin de año, paros y duelos se explican con una fila, nunca con una excepción en el código. | Un hueco explicado queda en `draw_gaps` con su causa, y uno sin explicar es el que alarma. |
| D16 | **Un incremental al día, a las 23:30 de Montevideo** | Una sola corrida diaria, después del último sorteo. Ver [Backfill e incremental](#backfill-e-incremental-uy-011). | La Nocturna termina ~21:20 y su HTML sale 3 a 13 minutos después (UY-003). Lo que llegue tarde queda `not_yet_published` y se pide al día siguiente (D9). |
| D17 | **Plata se reescribe por año** | Cada corrida reescribe entera la partición de cada año que tocó, sin merges. | Un año son unos 650 sorteos. Reescribir es idempotente y evita la lógica de upsert que Parquet no tiene. |
| D18 | **El backfill de plata es local primero** | Se parsea en local en la Fase 4 y en la nube con un `Map` de Step Functions por año (UY-042). | El bronce ya está en disco: la nube lo recibe subido (UY-042) y nunca vuelve a scrapear la historia. |
| D19 | **Los PDF de extracto históricos no se bajan** | El PDF es respaldo y se guarda solo desde la ingesta diaria en adelante. | Plata sale siempre del HTML (UY-003), y el PDF es una impresión del mismo PHP. |
| D20 | **GX en un job aparte, con GX ya empaquetado** | Un job de Glue 5.0 propio para las suites de UY, que no instala GX desde PyPI al arrancar. Ver [Calidad de datos](#calidad-de-datos-dq_flags-y-gx-uy-011). | En `master`, `--additional-python-modules` llegó a gastar ~21 minutos de arranque por corrida (PR-033.2). |
| D21 | **Fila por fila en el transform, el conjunto en GX** | El transform marca cada fila (`dq_flags`) o la manda a cuarentena. GX valida la tabla entera y es el gate antes de oro. | Una fila rara no debe frenar un año; una tabla rota, sí. |
| D22 | **El catálogo de `dq_flags` es cerrado** | Solo valen los nombres del catálogo. El escritor de plata rechaza cualquier otro, y GX lo comprueba. | Un flag escrito a mano en el código, con otro nombre o una errata, es un flag que ningún filtro de oro va a ver. |
| D23 | **Pruebas de propiedades sin `hypothesis`** | Un target de Make que recorre todo el bronce local, más tablas pequeñas de casos en el CI. Ver [Pruebas y riesgos](#pruebas-y-riesgos-uy-011). | El bronce real ya tiene 20 años de casos raros. Generar datos inventados no encuentra nada que esos 21.000 archivos no tengan. |

## Propuestas de este documento (se aprueban en G2)

| # | Propuesta | Por qué |
|---|---|---|
| P1 | **Un sorteo es un extracto publicado:** un juego en una fecha. La Revancha va dentro del 5 de Oro y la Tómbola dentro de cada Quiniela, como valores de `ball_type`. La clave de `draws` es (`country`, `operator`, `game`, `draw_date`). | Es como lo publica el sitio: un bloque en `ver_resultados`, un extracto, un PDF y un "Próximo sorteo" para los dos. La Revancha nunca se sorteó sin el 5 de Oro, ni la Tómbola sin su Quiniela. Si hace falta ver la Revancha como juego aparte, es un filtro o una vista de oro. |
| P2 | **Los horarios de la Quiniela van como columnas de `draws`**, sin una tabla `draw_timing`. | Son tres valores por sorteo (inicio, primera bolilla y fin) y solo existen en la Quiniela. Una tabla aparte obligaría a un join para nada. En el 5 de Oro quedan nulos. |
| P3 | **El bronce no se mueve.** Se queda en `data/uy/bronze/country=uy/source=…/year=…/`, que ya lleva el país. | Ya tiene el país, como pide D1. Mover ~20.000 archivos y reescribir el `bronze_key` del manifiesto no aporta nada. La organización por fuente es la correcta, porque `ver_resultados` trae varios juegos en un archivo. Esto reemplaza la ruta `game=…/draw_date=…` que el roadmap proponía para UY-021. |
| P4 | **El YAML se valida con dataclasses propias, sin pydantic.** Las dependencias nuevas (`pyyaml` y `pdfplumber`) van en un extra `uy` de `pyproject.toml`. | pydantic suma un binario al paquete de la Lambda solo para validar 4 archivos. Con un cargador estricto de ~100 líneas alcanza: rechaza claves que no conoce, comprueba tipos y cruza referencias. Hoy pydantic llega al repo solo de la mano de GX, que está fuera de la Lambda a propósito (PR-032). |
| P5 | **El guard de privacidad `DET_INVALIDAS` queda en el código, nunca en el YAML.** | Un error en un archivo de configuración nunca debe poder apagar el guard. El patrón vive en `sorteos/uy/` y se le pasa al cliente HTTP, con sus tests de UY-001 sin cambios. |
| P6 | **Se reordena la Fase 3:** UY-022 y UY-023 se juntan en un solo parser de `ver_resultados`. | Las dos épocas que suponía el roadmap no existen (D5 y [Evidencia](#la-estructura-del-html-casi-no-cambió)). Ver [Impacto en la Fase 3](#impacto-en-la-fase-3). |
| P7 | **`is_replacement` se define con los datos:** un número de la Tómbola es reposición si no está entre las dos últimas cifras de los 20 números de esa Quiniela. | Así se cumple en el 99,7% de los sorteos, y todas las excepciones son de 2006 ([Evidencia](#la-tómbola-sale-de-la-quiniela)). El mecanismo exacto (cómo se sortean las reposiciones) es una **hipótesis** hasta leer el reglamento. Lo que plata guarda no depende de ella. |
| P8 | **"Falla igual" quiere decir la misma firma**: el mismo `http_status` y el mismo `content_sha256`, o el mismo `detail` si no hubo respuesta. Se cuenta sobre las 3 últimas filas de `fetch_log` de esa clave, y la regla vale para **todas** las fuentes. | Un 403 que siempre devuelve los mismos 146 bytes es un archivo que no está. Un 403 distinto, o un timeout, puede ser un mal momento del sitio, y no debe cerrar la puerta. Ver [Manifiesto](#manifiesto-uy-011). |
| P9 | **`manual_overrides` es un CSV versionado en git**, junto a `calendar_events`, y el estado efectivo es el de la corrección cuando existe. | Es el mismo tratamiento que `calendar_events`: un cambio es una decisión revisada en un PR, no una edición de una base local. |
| P10 | **El tope para creer un anuncio pasa de 7 a 14 días.** **Aprobada por el owner el 2026-10-25.** | Con 7 días se descartan 4 anuncios **correctos** (Semana de Turismo 2020 y fin de año 2022, anunciados con 8 a 13 días) y el detector reporta huecos que la DNLQ había anunciado. Con 14, los 17 descartes que quedan son todos errores de tipeo. Ver [Detector de huecos](#cuánto-creerle-a-un-anuncio-p10). |
| P11 | **El incremental mira los últimos 7 días más toda clave no final del manifiesto.** **Aprobada por el owner el 2026-10-25.** | 7 = el *settle* de 3 días, más la ventana de 3 del detector, más uno. Las claves no finales de cualquier fecha (hoy, 39 `error`) se incluyen para que la regla de las 3 fallas (D11) termine de cerrarlas: si no, los 35 PDF de pozos de 2016–2026 solo se volverían a pedir con un backfill manual. |
| P12 | **El incremental pide las cuatro clases de fuente por defecto**: `resultados`, extractos PHP, PDF de extracto y PDF de pozos. **Aprobada por el owner el 2026-10-25.** | El default actual de `make uy-backfill` (`resultados,extractos`) es la razón por la que hasta el 2026-10-21 había solo 4 PDF de pozos en bronce. El backfill puede seguir eligiendo; el incremental no tiene por qué. |
| P13 | **Aprobada por el owner el 2026-10-25.** **El catálogo inicial tiene 7 flags** (`pozo_plata_equals_oro`, `amount_sources_differ`, `next_draw_unparsed`, `next_draw_implausible`, `draw_number_inferred`, `tombola_repeated_number`, `tombola_not_from_quiniela`), y **ninguno para el monto vacío**: el nulo ya lo dice (D6). | Cada uno sale de un caso verificado y dice cuántas filas marca hoy. Ver [el catálogo](#el-catálogo-d22-p13). |
| P14 | **Aprobada por el owner el 2026-10-25.** **GX se empaqueta como wheels en S3**, construidos como el layer (lock con hashes, `--platform`, Python 3.11), y Glue los instala con `--additional-python-modules` apuntando a S3 y sin PyPI. | Un zip por `--extra-py-files` solo sirve con código Python puro, y GX 1.20 requiere `numpy` y `scipy` (y `pydantic-core` con pydantic 2), que son extensiones compiladas: Python no carga un `.so` desde un zip. Qué trae ya Glue 5.0 y cuánto tarda el arranque se mide en UY-026 antes de elegir. |

---

## Evidencia verificada el 2026-10-16

Hecha con scripts desechables sobre el bronce local del backfill del 2026-10-04, **sin peticiones
nuevas**.

### La estructura del HTML casi no cambió

**Método:** para cada archivo se tomó el conjunto de clases CSS y de nombres de imagen, y se
registró en qué fecha aparece y desaparece cada uno.

| Fuente | Archivos | Resultado |
|---|---|---|
| Extracto del 5 de Oro | 2.072 | **Una sola plantilla** de 2006 a 2026 |
| Extracto de la Quiniela Nocturna | 5.935 | **Una sola plantilla** de 2006 a 2026 |
| Extracto de la Quiniela Vespertina | 4.943 | **Una sola plantilla** de 2006 a 2026 |
| `ver_resultados` | 6.908 | Solo dos cambios: el bloque del Kini desaparece después del **2013-12-27** (fin del juego) y entre el **2016-05-29 y el 2016-06-01** aparecen los botones de pozos e inválidas |

La "frontera de julio de 2016" que suponía el brief son esos botones, no un diseño nuevo. Este
método no detecta cambios de texto dentro de las mismas clases: eso lo cubren los fixtures por año
y la cuarentena de D5.

### El orden de los números por juego

**Método:** sobre los 10.877 extractos de Quiniela con datos (Nocturna y Vespertina) se separaron
los 20 números de 3 cifras de la Quiniela y los 20 de 2 cifras de la Tómbola. Un extracto de 2006
no tiene la Tómbola y quedó fuera.

| Juego | Lo verificado |
|---|---|
| Quiniela (20 de 3 cifras) | No sale ordenada en **ninguno** de los 10.877 extractos. El mismo número se repite dentro de un sorteo en **1.908 (17,5%)**, casi lo que da el azar con extracciones independientes de 000–999 (1 − e^(−190/1000) ≈ 17,3%). **Cada posición es una extracción aparte.** |
| Tómbola (20 de 2 cifras) | Sale **ordenada de menor a mayor en el 100%**. Los 31 sorteos con números repetidos son **todos de 2006** (la misma suciedad de 2006 de FINDINGS → `dq_flags`). |
| 5 de Oro y Revancha | Ordenados en el 100% (ya verificado en Q1). La bolilla extra va aparte. |

### `ver_resultados` y el extracto coinciden también en la Quiniela

Q1 comparó las dos fuentes solo para el 5 de Oro. Ahora se hizo para la Quiniela: en los
**10.877** sorteos, los 20 números de `ver_resultados` están **en el mismo orden** que en el
extracto, y los 20 de la Tómbola también coinciden. La única diferencia que dio el script fue un
falso positivo, el 2023-09-29: ese día el "Próximo" de la Nocturna dice `30 / 09 / 203` en las dos
fuentes, y el script tomó el `203` como un número más. Es otro error de tipeo compartido, como los
de 2006, y en plata debe quedar `next_draw_date` nulo con un `dq_flag`.

**Consecuencia:** `ver_resultados` alcanza como fuente principal de todos los juegos. El extracto
de la Quiniela agrega solo los horarios (P2).

### La Tómbola sale de la Quiniela

| Comprobación | Sorteos |
|---|---|
| Las dos últimas cifras de los 20 números de la Quiniela están **todas** en la Tómbola | 10.847 de 10.877 |
| Además, la Tómbola completa 20 con **tantos números nuevos como terminaciones repetidas** tuvo la Quiniela | 10.846 de 10.877 |
| Excepciones | 30 a 31, **todas de 2006** |

La Tómbola son las terminaciones distintas de la Quiniela más reposiciones hasta llegar a 20.
Coincide con lo que da el azar: el promedio esperado de reposiciones es 20 − 100·(1 − 0,99²⁰) ≈ 1,8,
la cifra que el roadmap ya anotaba para UY-032. Esto define `is_replacement` (P7) y da una
validación cruzada fuerte para UY-025.

### Los montos

| Fuente | Formas encontradas | Ejemplo |
|---|---|---|
| `ver_resultados` | `9,999,999.99` y `999,999.99`. Siempre con 2 decimales | `$ 110,629,426.70` |
| Extracto del 5 de Oro | `9.999.999,99` y `999.999,99`. Siempre con 2 decimales | `110.629.426,70` |
| Vacío | `$` sin monto (`ver_resultados`) y `0,00` (plantilla del extracto) | 2006-08-20 |

La Quiniela y la Tómbola no publican montos en estas fuentes.

---

## El paquete `src/sorteos/`

```
src/sorteos/
├── core/                      # no sabe de ningún país
│   ├── http_client.py         # el de UY-001: token bucket, backoff, caché, blocklist recibida por parámetro
│   ├── bronze.py              # almacén de bronce; el país entra como parámetro
│   ├── manifest.py            # el Protocol Manifest, SQLite, las 3 fallas y manual_overrides (UY-021)
│   ├── config.py              # carga y valida site.yaml y games/*.yaml (P4)
│   ├── money.py               # parse_amount(texto, estilo) -> Decimal | None (D6)
│   ├── shapes.py              # valida los números de un sorteo contra el YAML
│   └── silver.py              # esquemas pyarrow explícitos, escritura y cuarentena
└── uy/
    ├── site.yaml              # lo común a Uruguay: operador, URL base, zona horaria, moneda
    ├── games/
    │   ├── 5_de_oro.yaml
    │   ├── quiniela_vespertina.yaml
    │   └── quiniela_nocturna.yaml
    ├── reference/
    │   ├── game_rules.csv     # hoy en docs/uruguay/drafts/
    │   ├── calendar_events.csv
    │   └── manual_overrides.csv  # D10, P9 (UY-021)
    ├── privacy.py             # el patrón DET_INVALIDAS (P5)
    ├── sources.py             # arma las URLs a partir de los YAML
    ├── classify.py            # el de hoy, sin cambios
    ├── parsers/
    │   ├── resultados.py      # ver_resultados: todos los juegos del día
    │   ├── extracto_5_de_oro.py
    │   ├── extracto_quiniela.py
    │   └── pozos_pdf.py       # número de sorteo (pdfplumber)
    └── backfill.py            # la CLI de hoy
```

Un país nuevo es una carpeta hermana de `uy/` con su `site.yaml`, sus juegos y sus parsers. Lo que
resulte común a dos países sube a `core/` cuando exista el segundo, no antes.

### Migración desde `src/loteria_uy/` (en UY-020)

El bronce y el manifiesto **no se tocan** (P3). Solo se mueve el código:

1. `git mv` de los cinco módulos a sus lugares nuevos, para conservar la historia. `http_client.py`
   y `bronze.py` reciben el país y la blocklist por parámetro en vez de tenerlos escritos.
2. `sources.py` deja de tener URLs escritas a mano (`_PHP_PATHS`, `_PDF_LETTERS`,
   `PDF_EXTRACTS_FROM`, `_FIXED_CODES`) y las lee de los YAML. Los **nombres de las fuentes no
   cambian**, porque son la clave del manifiesto: así el backfill retoma donde quedó.
3. **Test de oro de las URLs:** cada fila del manifiesto guarda la URL que se pidió. El código nuevo
   tiene que reproducirlas todas: las ~20.000 en local (un target de Make), y una muestra fija de
   unas 50 filas, de todas las fuentes y épocas, como fixture para CI.
4. `pyproject.toml` pasa de `--cov=src/loteria_uy` a `--cov=src/sorteos` (es la línea que agregó
   esta misma rama). El `Makefile` cambia `loteria_uy.backfill` por `sorteos.uy.backfill`, con los
   mismos nombres de targets. Los tests pasan a `tests/unit/sorteos/`.
5. `src/loteria_uy/` se borra en el mismo PR, sin módulo puente: nadie más lo importa.

**Aceptación:** `make uy-report` da los mismos números antes y después, y el gate de 98 se
mantiene.

---

## Configuración: los YAML

### Qué es y qué no es

- **No es un dato.** El bronce guarda lo que publicó el sitio y plata guarda lo que entendimos de
  eso. El YAML son las **instrucciones** para pasar de lo uno a lo otro. Vive en git, junto al código,
  y viaja dentro del paquete de la Lambda.
- **Lo leen todos los pasos:**
  - el extractor, para saber qué URLs pedir;
  - el clasificador, para saber qué días se espera sorteo y desde qué hora;
  - el parser, para elegir la época;
  - las validaciones, para comprobar la forma de los números;
  - la escritura en plata, para poner `country`, `operator`, `game` y `currency`.
- **Lo que no lleva:** las reglas con vigencia y su resolución (`game_rules`) ni los eventos del
  calendario (`calendar_events`). Esas son datos que cambian con el tiempo y tienen fuente, así que
  son CSV en `reference/` que se cargan como tablas de plata.

### `site.yaml`: lo común al país

```yaml
country: "uy"
operator: "dnlq"
operator_name: "Dirección Nacional de Loterías y Quinielas"
base_url: "https://www.loteria.gub.uy"
timezone: "America/Montevideo"
currency: "UYU"
history_starts: "2006-08-11"
pages:
  resultados:                       # una página por día con todos los juegos
    path: "/ver_resultados.php"
    params: {vdia: "{day}", vmes: "{month}", vano: "{year}"}   # sin ceros, como el calendario del sitio
    money_style: "us"
    parser_epochs:
      - {version: 1, valid_from: "2006-08-11"}
```

### Un juego: `quiniela_nocturna.yaml`

```yaml
game: "quiniela_nocturna"
name: "Quiniela y Tómbola Nocturna"
site_code: 4                        # primer argumento de MostrarExtracto()
calendar:
  weekdays: ["mon", "tue", "wed", "thu", "fri", "sat"]   # nunca domingo (Q2)
  next_draw_label: "Próximo Nocturno"
  publish_after_local: "21:30"      # termina ~21:20 y el HTML sale 3-13 min después (UY-003)
sources:
  - {name: "resultados", role: "primary"}
  - name: "extracto_quiniela_nocturna"
    kind: "extracto_php"
    path: "/extractosweb/quiniela/nocturna/extracto_QN_S.php"
    role: "timing"                  # aporta los horarios (P2) y es el control cruzado
    parser_epochs: [{version: 1, valid_from: "2006-08-11"}]
  - name: "extracto_pdf_quiniela_nocturna"
    kind: "extracto_pdf"
    letter: "n"
    valid_from: "2018-11-30"
    role: "backup"                  # solo bronce, no se parsea (decisión del owner, UY-003)
numbers:
  quiniela: {count: 20, digits: 3, order: "drawn",  repeats: true}
  tombola:  {count: 20, digits: 2, order: "sorted", repeats: false, replacements_from: "quiniela"}
```

### Otro juego: `5_de_oro.yaml`

```yaml
game: "5_de_oro"
name: "5 de Oro y Revancha"
site_code: 5
calendar:
  weekdays: ["wed", "sun"]          # se esperan, pero el 12,6% cae otro día (C10)
  next_draw_label: "Próximo 5 de Oro y Rev."
  publish_after_local: "22:30"
sources:
  - {name: "resultados", role: "primary"}
  - name: "extracto_5_de_oro"
    kind: "extracto_php"
    path: "/extractosweb/5deOro/extracto_5_de_oro.php"
    money_style: "uy"
    role: "cross_check"
    parser_epochs: [{version: 1, valid_from: "2006-08-11"}]
  - {name: "extracto_pdf_5_de_oro", kind: "extracto_pdf", letter: "o", valid_from: "2018-11-30", role: "backup"}
  - {name: "pozos_5_de_oro", kind: "pozos_pdf", role: "draw_number"}   # la URL sale del link de la página
numbers:
  oro:      {count: 5, digits: 2, order: "sorted", repeats: false, range_rule: "rango_numeros"}
  extra:    {count: 1, digits: 2, range_rule: "rango_numeros", not_in: ["oro"]}
  revancha: {count: 5, digits: 2, order: "sorted", repeats: false, range_rule: "rango_numeros"}
prizes: ["oro", "plata", "revancha"]
```

`range_rule` apunta a una regla de `game_rules`. El rango 01–44 o 01–48 se resuelve con la fecha
del sorteo, no se escribe en el YAML.

### Reglas del cargador (P4)

- `yaml.safe_load`, y después el cargador estricto: una clave que no conoce es un error, y los
  tipos se comprueban. Los textos van **siempre entre comillas** en los YAML del repo, y el
  cargador exige `str` donde corresponde. Así un `no` (Noruega) nunca llega como `false`, ni una
  fecha como objeto `date`.
- Referencias cruzadas al arrancar: cada `range_rule` existe en `game_rules.csv`, cada
  `replacements_from` y cada `not_in` existen en `numbers`, y las épocas de una fuente no se
  superponen ni dejan huecos.
- Un test carga todos los YAML del repo. Una configuración rota falla en CI, nunca en producción.

---

## Plata

### Convenciones

- **Ruta:** `silver/<tabla>/country=uy/game=<juego>/year=<aaaa>/`. `game_rules` y
  `calendar_events` se parten solo por país.
- **Tamaño:** unos 13.000 sorteos y ~460.000 números en toda la historia. No hace falta nada más fino:
  por el piso de 10 MiB de Athena, partir más no ahorra plata (ver la memoria de PR-043.1).
- **Linaje** (como PR-045, más dos columnas): `ingested_at timestamp` (UTC), `run_id string`,
  `source_key string` (la clave de bronce de la que salió la fila), `source_sha256 string` y
  `parser_version string`. Van en todas las tablas.
- **Tipos explícitos:** cada tabla tiene su esquema pyarrow escrito en `core/silver.py`, con `int32`
  donde el catálogo dice `int`. Una columna que viene toda en `None` se escribe con su tipo, nunca
  como `Null`. Son las dos trampas de la memoria sobre tipos de Parquet. En la nube, las tablas se
  declaran en Terraform y no las crea un crawler (la lección de PR-045.2).
- **Datos sucios** (propuesta 1 de FINDINGS): se guarda el valor publicado y se marca en
  `dq_flags array<string>`. El vacío es nulo. Solo va a cuarentena lo que no se puede interpretar.
- **Cuarentena:** un sorteo que no parsea va **entero** a `silver/quarantine/` (fuente, fecha,
  `source_key`, `parser_version`, motivo y linaje), como en PR-044. Nunca quedan filas a medias en
  plata. Bronce guarda la página, así que la cuarentena no copia contenido.

### `draws`: un sorteo por fila (P1)

| Columna | Tipo | Notas |
|---|---|---|
| `country`, `operator`, `game` | string | D1. Por ejemplo `uy`, `dnlq`, `quiniela_nocturna` |
| `draw_date` | date | Clave natural junto con las tres de arriba |
| `draw_number` | int | Solo el 5 de Oro, y solo desde 2016 (PDF de pozos, C11). Nulo antes |
| `next_draw_text` | string | El "Próximo sorteo" tal como se publicó |
| `next_draw_date` | date | El mismo, interpretado. Nulo si no parsea (por ejemplo `30 / 09 / 203`), con su `dq_flag` |
| `started_local`, `first_ball_local`, `ended_local` | timestamp | Solo la Quiniela (P2). La hora **de reloj de Montevideo**, tal como se publica y sin zona, porque la puntualidad se mide contra la hora local (las 21:00). Nulos si el extracto los trae vacíos (2006) |
| `timezone` | string | `America/Montevideo`, de `site.yaml`. El instante UTC se deriva con `zoneinfo` y nunca con un -03:00 fijo, porque Uruguay tuvo horario de verano hasta 2015 (C5) |
| `cross_source_check` | string | `match`, `mismatch` o `not_checked` (extracto ausente) |
| `dq_flags` | array\<string\> | |
| linaje | | ver convenciones |

Solo los días con sorteo llegan a plata. Los `no_draw` viven en el manifiesto, y los huecos en
[`draw_gaps`](#detector-de-huecos-uy-011).

### `draw_numbers`: formato largo (D3)

| Columna | Tipo | Notas |
|---|---|---|
| `country`, `operator`, `game`, `draw_date` | | Referencia al sorteo |
| `ball_type` | string | `oro`, `extra`, `revancha` (5 de Oro); `quiniela`, `tombola` (Quiniela) |
| `position` | int | 1 a N en el orden publicado |
| `is_draw_order` | boolean | `true` si `position` es el orden de extracción (`order: drawn` del YAML). Está en la tabla para que quien use Athena lo vea sin leer el YAML |
| `number` | string | Con sus ceros: `'043'`, `'07'` |
| `is_replacement` | boolean | Solo la Tómbola (P7). Nulo en los demás tipos de bolilla |
| linaje | | |

Clave: (`country`, `operator`, `game`, `draw_date`, `ball_type`, `position`).

### `prizes`: solo el 5 de Oro

| Columna | Tipo | Notas |
|---|---|---|
| `country`, `operator`, `game`, `draw_date` | | Referencia al sorteo |
| `prize` | string | `oro`, `plata` o `revancha` |
| `pool_amount` | decimal(18,2) | D6. Nulo si está vacío |
| `currency` | string | `UYU`, sale de `site.yaml` |
| `winners_status` | string | `winners`, `no_winners` ("Sin Aciertos") o `unknown` (celda vacía, las 25 de Q1) |
| `winning_coupons` | int | D7. Cuántos cupones ganaron: `0` con "Sin Aciertos" y nulo con `unknown`. Los números se cuentan en memoria y nunca se escriben |
| `dq_flags` | array\<string\> | Por ejemplo, Pozo de Plata igual al de Oro (2006-12-06) |
| linaje | | |

Clave: (`country`, `operator`, `game`, `draw_date`, `prize`).

### `game_rules` y `calendar_events`

Salen de `src/sorteos/uy/reference/*.csv`, con las mismas columnas que los borradores de UY-004
([`game_rules_5_de_oro.csv`](../../src/sorteos/uy/reference/game_rules.csv) y
[`calendar_events.csv`](../../src/sorteos/uy/reference/calendar_events.csv)), más `country` y `operator`. Son datos de
referencia con su fuente y su vigencia, y se versionan en git porque cada cambio es una decisión
revisada. El escritor de plata los pasa a Parquet sin transformarlos.

---

## Parsers y montos

### Un parser por fuente, una época al arrancar (D5)

| Parser | Lee | Escribe |
|---|---|---|
| `resultados.py` | `ver_resultados`, todos los juegos del día, separados por su `MostrarExtracto('<código>', …)` | `draws`, `draw_numbers` y `prizes` (fuente principal) |
| `extracto_5_de_oro.py` | El extracto PHP | Nada propio: es el control cruzado de `draws`, `draw_numbers` y `prizes` |
| `extracto_quiniela.py` | El extracto PHP de cada turno | Los horarios de `draws` (P2), y el control cruzado de los números |
| `pozos_pdf.py` | El PDF de pozos (pdfplumber) | `draws.draw_number` |

Reglas comunes:

- **Parsear es una función pura** de los bytes de bronce a filas. No toca la red ni el reloj: el
  bloque "Sorteos para el día de hoy" se ignora porque trae la fecha de la descarga (Q1).
- **Cada parser declara la forma que espera.** Si falta un marcador o sobra un bloque, levanta un
  error con el motivo y el sorteo va a cuarentena. Nunca se rellena con un valor "probable".
- **Los cupones** se leen solo para contarlos (D7) y para comparar el conteo entre fuentes. No
  salen de la función.
- **Fixtures, uno por variante conocida:** 2006 sucio, con y sin Kini, antes y después de los
  botones de 2016, la plantilla vacía, el `error` de 2019, el "Próximo" mal tipeado y una Quiniela
  con números repetidos.

### `core/money.py` (D6)

```python
def parse_amount(text: str, style: Literal["us", "uy"]) -> Decimal | None: ...
```

- Primero quita el `$` y los espacios. Si no queda nada, devuelve `None` (el vacío de
  `ver_resultados`).
- `style` lo da la configuración de la fuente (`money_style`), nunca el valor.
- `"0,00"` en un extracto es el marcador de plantilla vacía y devuelve `None` (FINDINGS, calidad de
  2006).
- Lo que no encaja con la expresión regular del estilo levanta un error, y el sorteo va a
  cuarentena.

---

## Manifiesto (UY-011)

El manifiesto es la memoria de la ingesta: para cada fuente y fecha guarda **qué pidió, qué
respondió el sitio y qué concluyó el clasificador**. Es lo que evita pedir dos veces lo mismo y lo
que permite reanudar un backfill cortado. No es el calendario: qué *debería* haber habido ese día lo
decide el [detector de huecos](#detector-de-huecos-uy-011), que trabaja sobre plata y nunca
escribe el manifiesto (D9).

### Lo que ya existe (UY-001, verificado)

`src/loteria_uy/bronze.py` tiene dos tablas SQLite. `manifest` guarda una fila por
(`source`, `draw_date`) con su estado, el HTTP status, el hash de los bytes (`content_sha256`),
`attempts` y las fechas del primer y del último pedido. `fetch_log` guarda una fila por **cada**
pedido, también los repetidos. Bronce guarda bytes solo para los `draw`.

| Estado | Qué significa | ¿Final? | Hoy en el manifiesto |
|---|---|---|---|
| `draw` | Hay sorteo, y los bytes están en bronce | Sí | 21.173 |
| `no_draw` | `ver_resultados` vacío y con más de 3 días: ese día no hubo juegos | Sí | 458 |
| `not_yet_published` | Vacío, pero con menos de 3 días: se vuelve a pedir | No | 0 |
| `missing` | El juego figura en `ver_resultados` pero su fuente no tiene nada | Sí | 2 |
| `error` | El pedido o la clasificación fallaron: se vuelve a pedir | No | 39 |

Cifras medidas el 2026-10-25 sobre el manifiesto local, en solo lectura y sin peticiones nuevas
(21.672 claves, 21.677 pedidos en tres corridas: 2026-10-04, 10-14 y 10-21).

- **El *settle* funciona (observado).** Solo una clave pasó alguna vez por `not_yet_published`, y
  terminó en `draw` en la corrida siguiente.
- **Los dos `missing` son PDF de extracto que respondieron 404** (2019-01-07 y 2022-06-01).
  `classify_pdf` trata el 404 como vacío, así que después del *settle* el hueco queda registrado
  como final.
- **Los 39 `error` son dos grupos.** Por un lado los 4 días del paro de AFAL de 2019 en
  `resultados` (25, 26, 27 y 30 de septiembre, con `attempts = 2`), que el clasificador marca bien
  porque la página no se entiende ([FINDINGS, Q2](FINDINGS.md#los-4-días-error-de-septiembre-de-2019-paro-verificado)).
  Por otro, 35 PDF de pozos: **34 respondieron 403 con los mismos 146 bytes** (un solo
  `content_sha256`), y uno respondió 200 con 0 bytes. No es el 404 de los `missing`: el cuerpo es
  otro, así que el clasificador no puede tratarlos igual sin una regla nueva.

### El problema: un `error` se pide para siempre

Como `error` no es final, cada corrida vuelve a pedir esas 39 claves. En el backfill da igual,
pero en el incremental diario (una corrida al día, decidido el 2026-10-20) serían 39 peticiones inútiles por día, y
cada día que la DNLQ deje un PDF roto suma una más. Además, `attempts` cuenta todos los pedidos de
la clave, no cuántas veces seguidas falló de la misma forma, así que no alcanza para decidir.

### Tres fallas iguales pasan a `missing` (D11, P8)

Cuando un pedido da `error`, se miran las **3 últimas filas de `fetch_log`** de esa clave. Si las
tres son `error` con la **misma firma**, la clave pasa a `missing`, queda registrada y se informa
igual que cualquier otro `missing`.

- **Firma:** (`http_status`, `content_sha256`). Si no hubo respuesta (timeout, conexión), es el
  `detail` del error.
- **Por qué la firma y no solo el contador:** un 403 que siempre devuelve los mismos 146 bytes es
  un archivo que no está. Un 403 con otro cuerpo, o un timeout, puede ser un mal momento del sitio.
  Contar sin mirar la firma cerraría la puerta por tres cortes de luz.
- **Vale para todas las fuentes (P8).** También para `resultados`, aunque ahí las correcciones
  manuales llegan antes. Sin la regla, un `error` de `resultados` que nadie corrige se pediría para
  siempre.
- **Se puede deshacer.** `--refresh` sigue existiendo como herramienta manual para volver a pedir
  una clave final. En la v1 ninguna corrida automática lo usa (D12).

**Con los datos de hoy (observado):** los 35 PDF de pozos tienen `attempts = 1`, así que pasarían a
`missing` después de dos corridas más con la misma respuesta. El 200 con 0 bytes también tiene una
firma estable (el hash del contenido vacío), así que entra en la misma regla.

### Correcciones manuales: `manual_overrides` (D10, P9)

Hay días que el clasificador marca bien como `error`, pero que una persona puede explicar: el paro
de 2019 es el caso conocido. Para esos casos hay una tabla aparte, y **el manifiesto nunca se edita
a mano.**

| Columna | Ejemplo |
|---|---|
| `source` | `resultados` |
| `draw_date` | `2019-09-25` |
| `state` | `no_draw` |
| `calendar_event_date` | `2019-09-25`, la fila de `calendar_events` que lo explica |
| `reason` | `paro parcial de AFAL (OIS 2036)` |
| `decided_by` / `decided_on` | `owner` / `2026-10-20` |

- **El estado efectivo** de una clave es el de su corrección, si tiene una, y si no el del
  manifiesto. El backfill salta las claves cuyo estado efectivo es final, así que un día corregido
  deja de pedirse.
- **Por qué aparte:** si la corrección viviera en la fila del manifiesto, un `--refresh` la
  borraría, y se perdería lo que el código clasificó de verdad. Así quedan las dos cosas: lo que vio
  el clasificador y lo que decidió una persona, con su fuente.
- **Dónde vive:** `src/sorteos/uy/reference/manual_overrides.csv`, al lado de `calendar_events`.
  Es un dato de referencia revisado en un PR, igual que
  [`game_rules` y `calendar_events`](#game_rules-y-calendar_events).
- **Un `error` nuevo sigue pidiendo revisión humana.** La tabla no tiene comodines: cada fila es una
  fuente y una fecha.

### Una interfaz, dos backends (D12)

UY-021 define `Manifest` como un `Protocol` con lo que la ingesta usa hoy: `get`, `record`, el
estado efectivo y el historial de una clave. SQLite es la implementación local. **DynamoDB es la
candidata para UY-040**: clave de partición `source`, clave de orden `draw_date`, y el historial en
una tabla aparte o como ítems con sufijo. Esa elección se cierra en la Fase 5, no aquí.

### Lo que el manifiesto no hace

- **No guarda el hash de los datos.** `content_sha256` es el hash de los bytes. El hash de las
  filas canónicas que produce el parser va en el linaje de plata (UY-025), porque dos páginas con
  bytes distintos pueden traer los mismos datos.
- **No infiere el número de sorteo.** Cuando falta un PDF de pozos, el número se infiere en plata a
  partir de los vecinos consecutivos, con `dq_flags: draw_number_inferred` (owner,
  2026-10-21). Eso es del parser y del escritor de plata, no del manifiesto.
- **No decide si faltó un sorteo.** Eso es del detector de huecos.

### Los 4 días del paro ya tienen qué citar

El 2019-09-30 era el único de los 4 sin fila en `calendar_events`. `noticias.php` lo explica con el
**OIS N° 2039, "Sorteos suspendidos el lunes 30/09/2019"** (una petición, 2026-10-25). La misma
página trae dos OIS de esa semana que el borrador de UY-004 tampoco tenía: el **2040** (Vespertina
suspendida el martes 2019-10-01) y el **2041** (el 5 de Oro del miércoles 2019-10-02 pasa al
viernes 2019-10-04). Los tres coinciden con el manifiesto, y
[`calendar_events.csv`](../../src/sorteos/uy/reference/calendar_events.csv) pasa de 54 a 57 filas. Como con el OIS 2038,
los documentos no se leyeron: el contenido sale de su título, y la causa del 30 (el paro), de la
nota de [FocusGN del 2019-10-03](https://focusgn.com/latinoamerica/loterias-uruguayas-apuestas).

## Detector de huecos (UY-011)

El detector responde una sola pregunta: **¿faltó un sorteo que debía haber ocurrido?** No mira el
manifiesto, que dice lo que mostró la página (D9). Trabaja sobre los sorteos de plata, el
calendario de cada juego y `calendar_events`.

### Una función, dos usos (D13)

`expected_draws()` vive en `sorteos/core/gaps.py` y es pura: recibe la lista ordenada de sorteos de
un juego (`draw_date` y `next_draw_date`), el calendario del YAML (`calendar.weekdays`) y las filas
de `calendar_events`, y devuelve los huecos. No hace peticiones, no lee archivos y no conoce la
fecha de hoy, que llega como argumento.

- **El reporte del backfill** la corre sobre toda la historia y escribe `draw_gaps` completa.
- **La alarma del incremental** la corre en la corrida diaria de las 23:30 de Montevideo (decidido
  el 2026-10-20) y avisa solo de los huecos **abiertos** cuya ventana cerró desde la corrida
  anterior.

### La regla (D14)

1. **Fecha esperada.** Si el sorteo anterior anunció una fecha y esa fecha cae en
   (anterior, anterior + 14 días], se espera esa ([P10](#cuánto-creerle-a-un-anuncio-p10)). Si no anunció nada, o anunció algo imposible, se
   espera el siguiente día de `calendar.weekdays` (miércoles o domingo para el 5 de Oro, por
   ejemplo).
2. **Ventana.** El sorteo cuenta si ocurre entre la fecha esperada y 3 días después, porque la
   DNLQ traslada un sorteo al día siguiente sin cambiar el anuncio (31 de los 34 desaciertos del
   anuncio del 5 de Oro, [FINDINGS](FINDINGS.md#próximo-sorteo-predice-el-siguiente-verificado)).
3. **Un sorteo adelantado no es un hueco.** Si el sorteo siguiente ocurrió *antes* de la fecha
   esperada, no falta nada y no hay alarma. Pasa dos veces en 20 años (5 de Oro 2012-06-20,
   Nocturna 2022-12-24).
4. **Si no hay sorteo en la ventana, hay hueco.** Queda **explicado** cuando una fila de
   `calendar_events` de ese juego cae entre la fecha esperada y el sorteo que finalmente ocurrió
   (D15). Si no, queda **abierto**.
5. **Un anuncio descartado** deja `next_draw_implausible` en los `dq_flags` del sorteo que lo
   publicó. El sorteo es válido; lo que no sirve es su anuncio.
6. **Leer la fecha.** Se acepta `/`, `-`, `.` o espacios como separador, uno o varios seguidos
   (`12 / /02 / 2025`), el formato compacto `ddmmaaaa` y el año en 2 o 4 dígitos. **Nunca se
   corrige un dígito**: `30 / 09 / 203` y `30 / 07 / 25007` no se leen como fecha, así que
   `next_draw_date` queda nulo con `next_draw_unparsed`, en vez de convertirse en 2023 o 2007
   (owner, 2026-10-21).

### Medido sobre el bronce (verificado, 2026-10-25)

Con un script desechable sobre el bronce local y el manifiesto en solo lectura, sin peticiones.
Cada par es un sorteo y el siguiente del mismo juego. Las cifras de la Quiniela repiten las de la
medición del 2026-10-21.

| Juego | Pares | Aciertos con el tope anterior (7 días) | Aciertos con el tope de 14 días (P10) |
|---|---|---|---|
| 5 de Oro | 2.076 (2006-08-16 → 2026-10-18) | 99,71 % (2.070) | 99,81 % (2.072) |
| Quiniela Vespertina | 4.953 (2006-08-16 → 2026-10-20) | 99,96 % (4.951) | 99,98 % (4.952) |
| Quiniela Nocturna | 5.947 (2006-08-11 → 2026-10-20) | 99,95 % (5.944) | 99,97 % (5.945) |

Con el tope de 14 días quedan **5 desaciertos**, y ninguno es un error de la regla:

| Juego | Esperado | Ocurrió | Qué fue | En `calendar_events` |
|---|---|---|---|---|
| 5 de Oro | 2006-08-27 | 2006-09-03 | Las dos primeras semanas del sitio ([FINDINGS](FINDINGS.md#miércoles-o-domingos-sin-5-de-oro-y-sin-reemplazo-34-fechas-verificado), sin explicar) | No: **hueco abierto** |
| 5 de Oro | 2015-12-23 | 2015-12-27 | Fin de año | Sí (del brief, sin URL) |
| 5 de Oro | 2019-09-25 | 2019-10-01 | Paro de AFAL | Sí (OIS 2036 a 2039) |
| Vespertina | 2019-09-25 | 2019-10-02 | Paro de AFAL | Sí |
| Nocturna | 2019-09-25 | 2019-10-01 | Paro de AFAL | Sí |

Los adelantos (2012-06-20 y 2022-12-24) no cuentan como desacierto por el punto 3. Los demás
huecos conocidos (las 13 Semanas de Turismo y casi todos los fines de año) **no aparecen**: el
sorteo anterior ya anunciaba la fecha correcta, después del feriado, así que no faltó nada.

### Cuánto creerle a un anuncio (P10)

El tope existe para descartar los errores de tipeo. Con el tope original de 7 días se descartan 21
anuncios, pero **4 eran correctos**: la Semana de Turismo 2020 (el 3, 4 y 5 de abril anunciaron el
13, con 8 a 10 días de anticipación) y el fin de año 2022 (el 2022-12-21 anunció el 2023-01-03,
con 13). Al descartarlos, el detector espera un sorteo que la DNLQ ya había dicho que no iba a
haber, y reporta un hueco. El resultado no cambia mucho, porque `calendar_events` lo explica, pero
el sorteo queda marcado con `next_draw_implausible` cuando su anuncio era correcto.

Los otros 17 son errores de verdad: año equivocado (`2008` por `2009`, `2013` por `2023`), mes
equivocado (`16/12` por `16/11`), un año de más (`2208`) y un anuncio con la misma fecha del
sorteo. **El más cercano está a 31 días** (2010-11-11 anuncia el 2010-12-12), así que un tope de
14 días acepta los 4 correctos y sigue descartando los 17. Aparte quedan 2 que ni siquiera son una
fecha (`25007` y `203`, punto 6).

**Corrección a FINDINGS (Q1):** los sorteos del 5 de Oro del 2025-02-09 y del 2025-09-14 no
están "sin fecha". Traen `12 / /02 / 2025` y `17/ /09 / 2025`, con el separador repetido, y con
la regla del punto 6 anuncian bien el miércoles siguiente. **El
owner aprobó usar 14 el 2026-10-25.**

### `draw_gaps`

| Columna | Tipo | Notas |
|---|---|---|
| `country`, `operator`, `game` | string | D1 |
| `previous_draw_date` | date | El último sorteo antes del hueco |
| `expected_date` | date | Lo que esperaba la regla |
| `expected_from` | string | `announcement` o `calendar`: de dónde salió la fecha esperada |
| `window_end` | date | `expected_date` + 3 días |
| `next_draw_date` | date | El sorteo que finalmente ocurrió. Nulo si todavía no hubo |
| `status` | string | `explained` u `open` |
| `calendar_event_date` | date | La fila de `calendar_events` que lo explica. Nula si está abierto |
| linaje | | ver convenciones |

Un hueco se recalcula entero en cada corrida, como el resto de plata por año. Si mañana se agrega
la fila de `calendar_events` que lo explica, la próxima corrida lo pasa a `explained` sin tocar
nada más.

**El 2006-08-27 queda abierto para siempre**, salvo que aparezca una fuente. No alarma: la alarma
solo mira ventanas que cerraron desde la corrida anterior, y el reporte lo muestra como un hueco
documentado.

## Backfill e incremental (UY-011)

Los dos son la misma máquina, `Backfill` (UY-001): recorren un rango de fechas y, para cada día,
piden `ver_resultados` y después solo las fuentes de los juegos que esa página lista. Cambian el
rango, las fuentes y lo que pasa después de bajar.

### Lo que ya se midió (verificado)

Leído del manifiesto y de los logs locales, sin peticiones nuevas.

| Corrida | Peticiones | Duración | Qué hizo |
|---|---|---|---|
| Backfill completo, 2026-10-04 | 20.345 | 5 h 40 min | 2006-08-11 → 2026-10-03: `resultados` y extractos PHP, más 21 PDF de extracto y 4 de pozos |
| Muestra de PDF, 2026-10-14 | 226 | 3 min | PDF de extracto 2018–2026, para compararlos con el PHP (UY-003) |
| Puesta al día, 2026-10-21 | 1.106 | 17 min | Hasta 2026-10-20, más los 1.060 PDF de pozos |

- **El ritmo es el de cortesía:** 1 petición por segundo, con un solo worker (C2).
- **Un día normal son 3,2 claves** (mínimo 1, máximo 8), medido del 2026-09-01 al 2026-10-20 sin
  los PDF de extracto. Con ellos (P12) serían unas 5 (**hipótesis**: hasta la puesta al día no se
  pedían).
- **Reanudar ya funciona.** El manifiesto se escribe después de cada petición y las claves finales
  se saltan, así que un corte a mitad de corrida se retoma volviendo a correr el mismo comando. Una
  segunda corrida sobre un rango ya cerrado no hace ninguna petición.

### El incremental (D16, P11, P12)

**Cuándo.** Una vez al día, a las 23:30 de Montevideo. La Nocturna termina hacia las 21:20 y su
HTML aparece entre 3 y 13 minutos después; el PDF, a los 14 (UY-003). Si algo sale tarde, la clave
queda `not_yet_published` y se vuelve a pedir al día siguiente: no hace falta una segunda corrida.
En la nube va con un horario en `America/Montevideo` (UY-040), nunca con una hora UTC fija.

**Qué fechas (P11).** Los últimos 7 días, más toda clave que no sea final en el manifiesto, sea de
la fecha que sea. Los 7 días cubren el *settle* (3) y la ventana del detector (3). Las claves no
finales viejas son hoy 39 (los 4 días del paro y 35 PDF de pozos). Con D11 cada una se pide como
mucho 3 veces más antes de cerrarse, así que el costo es acotado.

**Qué fuentes (P12).** Las cuatro: `resultados`, los extractos PHP, el PDF de extracto (solo como
respaldo, sin parsear) y el PDF de pozos (el único origen del número de sorteo).

**Después de bajar**, en este orden:

1. Parsear lo nuevo y reescribir plata para cada año tocado (D17).
2. Correr `expected_draws()` sobre esos años y reescribir `draw_gaps` (D13).
3. Avisar de los huecos **abiertos** cuya ventana cerró desde la corrida anterior (UY-045).

Si el paso 1 falla, los pasos 2 y 3 no corren: un detector sobre una plata vieja avisaría de
huecos que no existen.

### Plata por año (D17)

Plata está particionada por año, y una corrida reescribe **entera** la partición de cada año que
tocó. Un año "tocado" es uno con al menos una clave del manifiesto que cambió de estado en la
corrida. Un día normal toca un año, y la primera semana de enero, dos.

Un año son unos 650 sorteos (640 en 2016 y 651 en 2025, contando 5 de Oro, Vespertina y Nocturna) y
unos 63 MB de bronce, así que reescribirlo cuesta segundos. A cambio, no hay lógica de *upsert*:
volver a correr da exactamente el mismo resultado.

### El backfill (D18, D19)

- **En local (Fase 4).** UY-030 parsea 2016 como piloto, porque cruza el cambio de layout, y UY-031
  parsea toda la historia. Todo sale del bronce que ya está en disco: el backfill de plata no hace
  peticiones.
- **En la nube (UY-042).** Se sube el bronce local y un `Map` de Step Functions parsea un año por
  ítem (21 años, 2006–2026). Que un año entre en los 15 minutos de una Lambda es una **hipótesis**
  hasta medir el tiempo de parseo en UY-030.
- **Lo que no se baja.** Los PDF de extracto históricos (D19): el respaldo empieza con la ingesta
  diaria. Las páginas finales tampoco se vuelven a pedir (D12).

## Calidad de datos: `dq_flags` y GX (UY-011)

Dos capas, cada una con su tarea (D21):

- **El transform**, fila por fila. Lo que se puede interpretar entra a plata **con el valor
  publicado** y, si algo no cuadra, con un `dq_flag`. Lo que no se puede interpretar (un número
  fuera de rango, 19 bolillas, una fecha que no coincide) va a cuarentena, como en PR-044.
- **GX**, sobre la tabla entera, después de escribir plata. Es el gate: si una suite falla, oro no
  se reconstruye y el aviso nombra la suite, la expectativa y la columna, como `NotifyDQFailure`
  en `master`.

### El catálogo (D22, P13)

Cada flag sale de un caso que se vio en los datos. Las cifras son de hoy, sobre el bronce local.

| Flag | Tabla | Cuándo se pone | Filas hoy | En oro |
|---|---|---|---|---|
| `pozo_plata_equals_oro` | `prizes` | El Pozo de Plata es igual al de Oro en el mismo sorteo | 1 (2006-12-06, [FINDINGS](FINDINGS.md#calidad-de-los-datos-de-2006-verificado)) | La dinámica de pozos lo excluye |
| `amount_sources_differ` | `prizes` | `ver_resultados` y el extracto dan montos distintos (D6). Plata guarda el de `ver_resultados` | 0 en los 2.072 sorteos comparados del 5 de Oro | Igual que el anterior |
| `next_draw_unparsed` | `draws` | Hay texto de "Próximo", pero no es una fecha (`30 / 09 / 203`). `next_draw_date` queda nulo | 2 | El detector usa el calendario |
| `next_draw_implausible` | `draws` | La fecha anunciada cae fuera de (sorteo, sorteo + 14 días] | 17 | El detector usa el calendario |
| `draw_number_inferred` | `draws` | El número de sorteo sale de los vecinos porque falta el PDF de pozos (owner, 2026-10-21) | Hasta 35 (los PDF de pozos con `error`) | Los análisis del número pueden excluirlo |
| `tombola_repeated_number` | `draws` | La Tómbola trae un número repetido | 31, todos de 2006 | Las frecuencias de la Tómbola lo excluyen |
| `tombola_not_from_quiniela` | `draws` | No se cumple P7: la Tómbola no es las terminaciones de la Quiniela más sus reposiciones | 30 a 31, todos de 2006 | `is_replacement` queda nulo en ese sorteo |

- **El monto vacío no lleva flag.** Por D6 ya es nulo, y nulo quiere decir eso. Un flag más
  diría lo mismo dos veces.
- **Tampoco llevan flag** los sorteos sin "Próximo" (117, casi todos de 2006): un nulo en
  `next_draw_text` ya lo dice.
- **Sumar un flag** es cambiar este documento, el catálogo del código y su test, en el mismo PR.
  El escritor de plata falla ante un nombre que no conoce.

### Dónde corre GX (D20, P14)

En un job de Glue 5.0 propio, separado del de Santa Lucía. La diferencia con `master` está en el
arranque: allí el job instala GX desde PyPI en cada corrida, y eso llegó a gastar ~21 minutos antes
de la primera línea del script (PR-033.2). Aquí GX llega ya empaquetado.

La propuesta (P14) es construirlo como el layer de Lambda: un lock con hashes, wheels para
`manylinux` y Python 3.11, subidos a S3, e instalados con `--additional-python-modules` apuntando a
esos archivos y sin PyPI. Un zip por `--extra-py-files` alcanza solo para código Python puro, y GX
1.20 requiere `numpy` y `scipy` (y `pydantic-core` si usa pydantic 2), que son extensiones
compiladas: Python no las carga desde un zip, salvo que Glue 5.0 ya las traiga. **Hipótesis:** que instalar desde S3 sin
resolver dependencias baje el arranque a segundos. UY-026 lo mide antes de cerrarlo.

Las lecciones de `master` que se repiten tal cual:

- **Las expectativas se derivan de los datos** (PR-032). Cada una se corre contra la plata local
  completa de UY-031 antes de entrar a la suite. Si falla con datos reales, se revisa la
  expectativa, nunca el dato.
- **GX con versión fija y suites versionadas** (PR-034): el JSON de las suites está en git y un
  test comprueba que coincide con el código que lo genera.
- **Las expectativas que dependen de una tabla de referencia se arman al correr** (PR-049). El rango
  del 5 de Oro sale de `game_rules`, no de una constante.

### Las suites (UY-026)

Cada expectativa cita su evidencia. Es la lista de partida; UY-026 la confirma contra los datos.

| Tabla | Expectativa | Evidencia |
|---|---|---|
| `draws` | (`country`, `operator`, `game`, `draw_date`) es única | P1 |
| `draws` | `game` está en {`5_de_oro`, `quiniela_vespertina`, `quiniela_nocturna`} | El alcance de la v1 (el Kini queda para UL2) |
| `draws` | La Quiniela nunca cae en domingo, y la Vespertina nunca en sábado | Q2 (verificado en toda la historia) |
| `draws` | `dq_flags` solo tiene nombres del catálogo | D22 |
| `draws` | `draw_number` solo existe en el 5 de Oro, es único por juego y es nulo antes de 2016-06-01 | C11 y el inicio del PDF de pozos |
| `draws` | Los horarios son nulos en el 5 de Oro | P2 |
| `draw_numbers` | Cada Quiniela tiene 20 números de 3 cifras, en las posiciones 1 a 20 | D3, 10.877 extractos |
| `draw_numbers` | Cada Tómbola tiene 20 números de 2 cifras, ordenados; sin repetidos desde 2007 | La evidencia de la Tómbola: los 31 con repetidos son de 2006 |
| `draw_numbers` | Cada 5 de Oro tiene 5 de Oro, 1 extra que no está entre ellos y 5 de Revancha | El YAML del 5 de Oro |
| `draw_numbers` | Los números del 5 de Oro están en el rango de su época: 01–44 hasta el 2014-03-16 y 01–48 desde el 2014-03-19 | `game_rules` (Q8), armada al correr |
| `prizes` | `currency` es `UYU` y todo monto es nulo o mayor o igual que 0 | D6 |
| `prizes` | `winning_coupons` es 0 si y solo si `winners_status` es `no_winners`, y nulo si y solo si es `unknown` | D7 |
| todas | Toda clave de `draw_numbers` y `prizes` existe en `draws` | PR-049 |
| `draw_gaps` | `status` está en {`explained`, `open`}, y `explained` si y solo si `calendar_event_date` no es nulo | D13, D15 |

## Pruebas y riesgos (UY-011)

### Tres niveles de prueba (D23)

| Nivel | Dónde corre | Qué prueba |
|---|---|---|
| **Fixtures** | CI, en cada PR | Una página real por caso conocido, con el resultado esperado escrito a mano |
| **Tablas de casos** | CI, en cada PR | Funciones puras con entradas cortas: montos, fechas del "Próximo", firmas de falla, `expected_draws()` |
| **Propiedades** | Local, `make uy-properties` | Las reglas de D3 y P7 sobre **todo** el bronce: 21.173 archivos, sin peticiones |

El CI no tiene el bronce, que pesa 1,1 GB y no se versiona. Por eso las propiedades corren en local
y su resultado (cuántos archivos, cuántas violaciones por regla) se pega en el PR que cambia un
parser, igual que un plan de Terraform.

### Fixtures que faltan

Hoy hay 11 fixtures y 53 tests (backfill, clasificador, cliente HTTP y privacidad). Los parsers
necesitan uno por cada caso de este documento. **Todos salen del bronce local**, pasados por
`scripts/uy_redact_fixture.py` (sin enlaces `DET_INVALIDAS` y con cupones falsos, C7), y se
commitean byte por byte con `SKIP=trailing-whitespace`.

| Caso | Fecha y fuente | Para qué |
|---|---|---|
| Pozo vacío (`$` y `0,00`) | 2006-08-20, `ver_resultados` y extracto | Nulo, nunca 0 (D6) |
| Pozo de Plata igual al de Oro | 2006-12-06 | `pozo_plata_equals_oro` |
| Tómbola con un repetido | Uno de los 31 de 2006 | `tombola_repeated_number` |
| Quiniela con un número repetido | Cualquiera de 2025 (el 17,5 % de los sorteos) | Que la clave sea la posición (D3) |
| "Próximo" con año de 3 cifras | 2023-09-29, Nocturna (`30 / 09 / 203`) | `next_draw_unparsed` |
| "Próximo" con separador repetido | 2025-02-09, 5 de Oro (`12 / /02 / 2025`) | Que se lea (regla E) |
| "Próximo" con año de 2 cifras | Uno de los 4 de Q1 (`03 / 06 / 09`) | Que se lea |
| "Próximo" de 13 días | 2022-12-21, 5 de Oro | Que P10 lo acepte |
| Celda de ganadores vacía | Una de las 25 de Q1 | `winners_status = unknown`, nunca `no_winners` |
| "Sin Aciertos" en sus variantes | Una por grafía (`sin acierto`, `SIN ACIERTO`…) | Normalización |
| Rango 01–44 y 01–48 | El último sorteo antes del 2014-03-16 y el primero desde el 2014-03-19 | La época de `game_rules` |
| PDF de pozos | Uno de 2016 y uno de 2026 | El número de sorteo |

### Riesgos y supuestos

Lo que este diseño da por bueno sin haberlo podido confirmar del todo:

| Riesgo | Qué pasa si falla | Cómo se detecta |
|---|---|---|
| **El bronce está en un solo disco.** Hasta UY-042 vive en `data/uy/`, más una copia en `~/backups/loteria-uy-2026-10-25/` | Volver a bajarlo lleva ~6 horas a 1 req/s. El 2026-10-25 se borró del disco por un `git switch` y se recuperó de la copia que #103 había subido a `master` por error; esa copia quedó congelada en el 2026-10-21 (PR-049.1) | Subirlo a S3 es lo primero de la Fase 5 (UY-042). Hasta entonces, el respaldo se rehace después de cada backfill |
| **El sitio puede empezar a bloquear.** Hoy responde sin CDN ni WAF, también desde AWS (UY-005) | El incremental falla con 403 | Las firmas de falla (P8) separan un 403 nuevo de los 34 viejos, y la alarma de huecos (UY-045) avisa en 3 días |
| **El sitio regenera las páginas** con la plantilla de hoy | Una página vieja pedida otra vez no es byte a byte la misma (48.072 contra 48.803 bytes el 2019-09-25) | Nunca se vuelve a pedir una página final (D12), y el hash de los datos va en el linaje (UY-025) |
| **Un año entra en una Lambda de 15 minutos** (D18) | El `Map` de UY-042 corta por timeout | Se mide en UY-030 con 2016 |
| **GX arranca rápido desde wheels en S3** (P14) | El job vuelve a gastar ~20 minutos de arranque | Se mide en UY-026 |
| **Los datos tipeados de 2006** comparten el error en las dos fuentes | La comparación entre fuentes no los corrige | Los flags los marcan y oro filtra por métrica (FINDINGS) |
| **Huecos sin explicación:** 2006-08-27/30 y las reglas anteriores a 2012 | Quedan abiertos o sin fuente | Están documentados como huecos aceptados (G1) |
| **Uruguay vuelve a tener horario de verano** | Las horas UTC de la Quiniela se corren una hora | Las horas se guardan locales y el UTC sale de `zoneinfo` (C5) |
| **Los cupones reales siguen en el historial de git** (antes de UY-011.1) | Están en un repo público | Aceptado por el owner. El escáner de fixtures impide que entren nuevos |

## Impacto en la Fase 3

Propuesta P6. La tabla definitiva del roadmap se reescribe al cerrar G2.

| PR | Antes | Ahora |
|---|---|---|
| UY-020 | Esqueleto, YAML y registro | Igual, más la [migración](#migración-desde-srcloteria_uy-en-uy-020) y el test de oro de las URLs |
| UY-021 | Manifiesto y bronce con rutas `game=…/draw_date=…` | El `Protocol`, la regla de las 3 fallas y `manual_overrides` ([Manifiesto](#manifiesto-uy-011)). **El bronce no se mueve** (P3) |
| UY-022 | Parser de `ver_resultados` 2007 → 2016-06 | **Un solo parser de `ver_resultados`** para 2006–2026 |
| UY-023 | Parser de `ver_resultados` desde 2016-07 | **Parsers de los extractos PHP** (5 de Oro y Quiniela con horarios) |
| UY-024 | Parsers de extractos (HTML y PDF) | **Parser del PDF de pozos** (número de sorteo) y `core/money.py` completo |
| UY-025 a 027 | | Sin cambios. En UY-025, la validación de la Tómbola pasa a ser la de P7 |

## Lo que queda para UY-011

- ~~El manifiesto~~: escrito en [Manifiesto](#manifiesto-uy-011).
- ~~El detector de huecos~~: escrito en [Detector de huecos](#detector-de-huecos-uy-011).
- ~~Backfill e incremental~~: escrito en [Backfill e incremental](#backfill-e-incremental-uy-011).
- ~~El catálogo de `dq_flags` y las suites de GX~~: escritos en
  [Calidad de datos](#calidad-de-datos-dq_flags-y-gx-uy-011).
- ~~El plan de pruebas y los riesgos~~: escritos en [Pruebas y riesgos](#pruebas-y-riesgos-uy-011).

**UY-011 está completo.** El documento entero es lo que el owner aprueba en **G2**.
