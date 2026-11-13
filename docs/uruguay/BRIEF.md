# Contexto y rol

Eres mi asistente de ingeniería de datos. Estoy evaluando un nuevo pipeline de portafolio (Data Engineer) con datos de las loterías oficiales de Uruguay, y quiero reutilizar la arquitectura de mi pipeline existente de la Lotería Santa Lucía de Guatemala. Antes de leer o proponer cambios, inspecciona ese repo para ver sus convenciones (estructura, IaC, tests, CI, orquestación) y respétalas.

Objetivo del proyecto: ingesta, calidad de datos y análisis descriptivo (por ejemplo, auditoría de aleatoriedad). NO es predecir sorteos ni "ganar la lotería". El valor está en la ingesta de una fuente real sin documentación, el backfill, la validación y el diseño extensible: un adaptador por juego, configuración por YAML, y luego otros países (Argentina, Brasil, Chile).

Esta fase es de EXPLORACIÓN Y EVALUACIÓN. No construyas todavía el scraper completo.

# Alcance y prioridades (main goal)

**Objetivo principal:** los tres juegos siguientes, en este orden de prioridad de análisis:

1. **5 de Oro + Revancha**
2. **Quiniela Vespertina** (y su Tómbola)
3. **Quiniela Nocturna** (y su Tómbola)

Nota: NO existe sorteo matutino. Los dos turnos diarios de Quiniela y Tómbola son Vespertino (~15:00) y Nocturno (~21:00). Si ves "matutina" en algún lugar de este proyecto, es un error de nomenclatura: significa Nocturna.

**Secundarios (solo exploración, fuera del alcance de la primera versión):** Lotería Uruguaya y Kini (histórico, descontinuado). El diseño debe poder incorporarlos luego sin reescribir nada, pero no inviertas tiempo de implementación en ellos hasta que los tres juegos principales estén definidos.

# Sitio y política de acceso

- Sitio: `https://www.loteria.gub.uy` (Dirección Nacional de Loterías y Quinielas, DNLQ, bajo el Ministerio de Economía y Finanzas).
- `robots.txt` (observado): solo tiene grupos para Googlebot, Googlebot-Image y AdsBot-Google, todos con `Disallow:` vacío. No hay grupo para otros user-agents, o sea no hay restricciones. Aun así: User-Agent identificable con contacto, máximo 1 request por segundo, reintentos con espera creciente ante 429/5xx, y nunca volver a pedir lo que ya esté cacheado en bronce. Revisar términos de uso del sitio queda como tarea pendiente (no soy abogado ni tengo conclusión legal).

# Juegos identificados (todos en el mismo sitio)

1. **5 de Oro + Revancha** (PRINCIPAL): miércoles y domingo, ~22:00 (transmitido por Canal 12). Histórico desde 07/01/2007 (el más antiguo que encontré).
2. **Quiniela y Tómbola** (PRINCIPAL): dos sorteos por día, Vespertina (~15:00) y Nocturna (~21:00). NO existe sorteo matutino (el bloque "Sorteos para el día de hoy" del sitio lista solo esos dos). En 2010 el "Próximo" posterior a un viernes era el lunes, lo que sugiere que no había sorteos en fin de semana en esa época (NO verificado; verificar cuándo y si cambió).
3. **Lotería Uruguaya** (secundario): la frecuencia mensual es dato mío, NO verificado. En la página de 2010-09-03 aparece con "Serie de Lotería Nro: 30" y 20 premios de 5 cifras con su monto (el mayor, $6.000.000). Es un juego con cuota de apuestas en descenso (~3% en 2025).
4. **Kini** (secundario): juego descontinuado, último sorteo 31/01/2014. En la página de 2010-09-03 muestra 5 números, "Pozo Kini" y "Sin Aciertos". El "Próximo Kini" de ese viernes fue un lunes, así que no es diario.
5. La página también menciona "4 de la Suerte" con varias modificaciones de fecha de inicio (NO sé si llegó a lanzarse).

Contexto de mercado (fuente: reportes de prensa sobre datos de la DNLQ): las apuestas de 2025 sumaron unos USD 677 millones (+5,3% vs 2024). Supermatch ~29%, Quiniela 27%, Tómbola / 5 de Oro / Quiniela Instantánea ~13% cada una.

# URLs de referencia

## Permitidas (puedes sondearlas con las reglas de cortesía)

Extractos oficiales (parámetros con dos dígitos):

- 5 de Oro, el sorteo más antiguo que encontré (07/01/2007):
  `https://www.loteria.gub.uy/extractosweb/5deOro/extracto_5_de_oro.php?vdia=07&vmes=01&vano=2007`
- Quiniela Vespertina, sonda de fecha temprana (02/01/2007; NO verificado que devuelva datos):
  `https://www.loteria.gub.uy/extractosweb/quiniela/vespertina/extracto_QV_S.php?vdia=02&vmes=01&vano=2007`
- Quiniela Nocturna, sonda de fecha temprana (02/01/2007; NO verificado que devuelva datos):
  `https://www.loteria.gub.uy/extractosweb/quiniela/nocturna/extracto_QN_S.php?vdia=02&vmes=01&vano=2007`

Pozos del 5 de Oro (PDF sin datos personales):

- `https://www.loteria.gub.uy/invalidas/06072016/ORO_06072016_RES_INFORMACION_DE_POZOS.PDF`

Página consolidada por fecha:

- `https://www.loteria.gub.uy/ver_resultados.php?vdia=3&vmes=9&vano=2010`

## EXCLUIDAS (NO pedir, NO descargar, NO parsear; solo para la lista de bloqueo y el test)

Estos archivos contienen una columna "Cédula Id." con lo que parecen cédulas de identidad. Se listan aquí únicamente para construir el patrón de exclusión y su test automático. Nunca los abras ni los uses como fixtures:

- `https://www.loteria.gub.uy/invalidas/20160706/TDI_06072016_DET_INVALIDAS_GENERAL_TELEFONICAS.PDF`
- `https://www.loteria.gub.uy/invalidas/20160706/QDI_06072016_DET_INVALIDAS_GENERAL_TELEFONICAS.PDF`
- `https://www.loteria.gub.uy/invalidas/06072016/ORO_06072016_DET_INVALIDAS_GENERAL_TELEFONICAS.PDF`

Patrón de exclusión propuesto: cualquier URL cuyo nombre de archivo contenga `DET_INVALIDAS`.

# Endpoints observados

## A. Página consolidada por fecha

`https://www.loteria.gub.uy/ver_resultados.php?vdia=3&vmes=9&vano=2010`

- Parámetros sin cero a la izquierda (el servidor normaliza el orden a vano, vdia, vmes).
- HTML renderizado en servidor (verificado con un fetch para 2010-09-03: todo el contenido estaba en el HTML, sin JS).
- Contenido de esa fecha: Lotería Uruguaya, Quiniela+Tómbola Vespertina, Quiniela+Tómbola Nocturna y Kini. El 5 de Oro no apareció (era viernes). En capturas de 2016 el 5 de Oro sí aparece (números, bolilla extra, pozos y cupones, Revancha). Si aparece en el HTML estático de todos los años, NO está verificado.
- Hay un selector de mes/año (2007–2026). Un bloque "Sorteos para el día de hoy" muestra siempre la fecha actual, no la pedida: NO debe parsearse como si fuera el sorteo solicitado.
- Los encabezados usan nombres de mes en español con "Setiembre" (no "Septiembre"), por ejemplo "Viernes 03 de Setiembre de 2010". Usar los parámetros de la URL como fuente de verdad de la fecha y el encabezado solo como validación cruzada.
- Enlaces a metadatos oficiales (no explorados aún): `ver_calendario.php` (calendario de sorteos), `ver_estadisticas.php` (estadísticas de números), `DCpG_2026.php` (sorteos especiales de billetes no premiados), `tablero_online.php`, y una lista de resoluciones.
- Esa lista de resoluciones incluye suspensiones y traslados por paro: 24/09/2014 (suspensión Ves./Noc. y traslado del 5 de Oro), 17/12/2014 (Vespertino), 26/06/2015 (Vespertino), 26/08/2015 (5 de Oro movido al 27/08), 23/12/2015 (Ves./Noc. y traslado del 5 de Oro). También hay una modificación al 5 de Oro (As 176/2014) y límites de horario de apuestas desde 02/05/2014. Estos eventos explican huecos y fechas movidas: guardarlos como dimensión calendario con la URL de la resolución.

Layout 2010 (observado, texto del HTML):

- Quiniela: dos columnas × 10 filas de números de 3 cifras. Posición 1–10 en la columna izquierda y 11–20 en la derecha (inferido por orden; las posiciones NO vienen como texto).
- Tómbola: dos columnas × 10 filas de 2 cifras, ordenadas ascendente al leer fila por fila.
- Ruido a ignorar: "Número del Premio", "gif_trasparente", "separador".
- Cada bloque trae "Próximo Vespertino/Nocturno: dd / mm / yyyy".

Layout desde julio de 2016 (observado en capturas): posiciones numeradas 1–20 en dos columnas, Tómbola en dos columnas ordenadas, y enlaces "Q. INVÁLIDAS" y "T. INVÁLIDAS" (ver la sección de exclusión de datos personales). El bloque del 5 de Oro tiene "Pozo de Oro", "Pozo de Plata", cupones, "Sin Aciertos", Revancha y los enlaces "INVALIDAS" y "POZOS". Los montos en este HTML usan formato estilo EE.UU. (`35,409,043.86`).

## B. Extractos oficiales por juego

Rutas observadas (parámetros con dos dígitos en mis ejemplos):

- 5 de Oro: `/extractosweb/5deOro/extracto_5_de_oro.php?vdia=17&vmes=01&vano=2007`
- Quiniela Vespertina: `/extractosweb/quiniela/vespertina/extracto_QV_S.php?vdia=02&vmes=09&vano=2008`
- Quiniela Nocturna: `/extractosweb/quiniela/nocturna/extracto_QN_S.php?vdia=02&vmes=09&vano=2008`
- Lotería Uruguaya y Kini: ruta NO descubierta (secundarios). Inspeccionar con DevTools (el enlace "Ir al Extracto Oficial" apunta a `#`, probablemente se abre por JS).

Comportamiento observado:

- **Siempre responde HTTP 200, incluso si ese día no hubo sorteo.** En ese caso devuelve la plantilla vacía: la fecha aparece como `//`, los pozos como `0,00`, no hay bolillas ni "Próximo Sorteo". Observado con 16/09/2025 y 18/09/2025 (sin sorteo) frente a 17/09/2025 (sorteo). Mi hipótesis es que es PHP antiguo que renderiza la plantilla aunque la consulta no devuelva fila. NO es un 404, así que no se puede validar por código de estado.
- El pie de página cita el Decreto 286/19 incluso en extractos de 2007 y 2008. Eso indica que el HTML se regenera desde una base de datos con la plantilla actual y NO es el documento original de esa fecha. Guardar el HTML crudo con fecha de descarga.
- Después de ~2010, en el navegador algunas URLs descargan un PDF en vez de renderizar HTML (observado por el usuario). Cambiar los parámetros de la URL sigue devolviendo datos reales y los valores coinciden con el PDF. NO inspeccioné `Content-Type` ni `Content-Disposition`. El PDF de 2025 tiene firma digital de la escribana y texto seleccionable (no necesita OCR). Al extraer el texto de un PDF, las columnas se mezclan (ej: `570346960-0 Sin Aciertos` en una línea).
- Encoding: en la página de 2008 aparece `Esc. Fernando Pe?aloza`. La `ñ` ya llega como `?` desde el origen.
- Estructura del extracto de 5 de Oro: fecha con día de semana, 5 números, "Bolilla Extra:", "POZO DE ORO", "POZO DE PLATA", líneas "Cupón Nro:", Revancha con 5 números y "POZO REVANCHA", "Próximo Sorteo: dd / mm / yyyy". Hay un artefacto `separador` entre cupones. Los cupones tienen formato `#########-#`. "Vacío" es distinto de "Sin Aciertos", y el parser debe distinguirlos. En 2007 los cupones aparecían bajo Plata y el de Oro vacío; en 2025 el cupón de Oro tiene valor y Plata dice "Sin Aciertos".
- Estructura del extracto de Quiniela: fecha, 20 números en 2 columnas (las posiciones son imágenes, así que al copiar el texto todas las filas dicen `01`), "Inicio", "Fin" y "Primero" con horas, Tómbola en 4 filas de 5, y "Próximo Sorteo".
- Formato de montos: en PDFs y extractos `42.501.146,34` (puntos de miles, coma decimal). En el HTML de ver_resultados de 2016, `35,409,043.86`. El parser de montos debe ser específico por fuente y usar `Decimal`.

## C. Pozos del 5 de Oro (PDF)

`/invalidas/06072016/ORO_06072016_RES_INFORMACION_DE_POZOS.PDF`: contiene número de sorteo (1857), fecha del sorteo, hora de emisión y los tres montos (Oro, Plata, Revancha) en formato `35.409.043,86`. No contiene datos personales y sirve para validar los pozos. Existe desde ~julio de 2016 (observado). La carpeta usa `aaaammdd` para Quiniela/Tómbola (`/invalidas/20160706/`) y `ddmmaaaa` para el 5 de Oro (`/invalidas/06072016/`).

Números de sorteo vistos: Quiniela Vespertina 01/07/2016 = 2543; 5 de Oro 06/07/2016 = 1857, 09/07/2017 = 1960, 08/07/2026 = 2891. Encajan con 2 sorteos por semana. Hipótesis: el número de sorteo sirve como clave natural y para detectar huecos (si pasa de 1857 a 1859, falta uno).

# Reglas de los juegos

- **Quiniela**: 20 números de 3 cifras (000–999), cada uno con posición 1–20. Se apuesta a 1, 2 o 3 últimas cifras; pagan 7×, 70× y 500× lo apostado por premio. Según descripciones de terceros (no de la DNLQ): tres esferas de bolillas 0–9 arman el número y una cuarta de 01–20 define la posición, así que cada número es independiente y puede repetirse. Con 20 tiradas sobre 1.000 valores se espera algún repetido en ~17% de los sorteos (cálculo analítico mío). Los repetidos son normales y NUNCA son un error de parseo.
- **Tómbola**: 20 números DISTINTOS de 2 cifras (00–99), derivados de las dos últimas cifras de la Quiniela del mismo turno. Si hay repetidos, se sortean otros hasta completar 20 distintos. Verificado a mano en 4 sorteos: 02/09/2008 Vespertina (3 reemplazos: 07, 64, 84), 03/09/2010 Vespertina (0), 03/09/2010 Nocturna (2: 19 y 92), 03/09/2026 Vespertina (2: 43 y 69). Con 20 tiradas sobre 100 valores se esperan ~1,8 reemplazos por sorteo. Propuesta: columna `is_replacement` = número de la Tómbola que no está entre las últimas dos cifras de la Quiniela.
- **5 de Oro**: 5 números principales + "Bolilla Extra"; Pozo de Oro, Pozo de Plata, Cupones, y Revancha (otro sorteo de 5 números, con su pozo). El rango válido NO está verificado: fuentes de terceros indican 01–48 (en lo visto el máximo fue 46). No lo hardcodees hasta confirmarlo con las resoluciones. Las reglas cambiaron en varios años (mencionados: 2012, 2014, 2019, 2020), todo por verificar; necesitamos una tabla `game_rules` con vigencias.

# EXCLUSIÓN POR PRIVACIDAD (obligatoria)

Los PDF `*_DET_INVALIDAS_GENERAL_TELEFONICAS.PDF` (los enlaces "Q. INVÁLIDAS", "T. INVÁLIDAS" e "INVALIDAS" bajo los sorteos) contienen una columna "Cédula Id." con lo que parecen cédulas de identidad uruguayas ligadas a apuestas telefónicas anuladas. La DNLQ las publica, incluso en 2026. Para este proyecto:

- NUNCA pedir, descargar, parsear, guardar ni registrar en logs esos archivos.
- Implementar una lista de URLs excluidas por patrón de nombre (`DET_INVALIDAS`) en el cliente HTTP, más un test automático que falle si alguna petición coincide con ese patrón.
- Documentar esta decisión de privacidad en el README (Ley 18.331 de Uruguay sobre protección de datos personales; sin conclusión legal).
- No copiar ningún valor de esos documentos a fixtures ni a documentación.
- Solo `RES_INFORMACION_DE_POZOS` está permitido de esa carpeta.

# Hipótesis de diseño (para evaluar, no son decisiones)

1. **Dos capas de ingesta.**
   - Capa 1: barrido diario sobre `ver_resultados.php` desde 2007-01-01 hasta hoy (~7.200 peticiones, ~2 h a 1 req/s), idempotente y paralelizable con pocos workers. Una petición por día trae todos los juegos.
   - Capa 2: enriquecimiento con `extractosweb/*` y el PDF de pozos para lo que la capa 1 no tenga (por ejemplo `Inicio`/`Fin`/`Primero` de Quiniela, y pozos y cupones del 5 de Oro si no están).
2. **Manifiesto por fecha y fuente:** fecha, fuente, estado HTTP, estado lógico (`draw`, `no_draw`, `not_yet_published`, `error`), hash del contenido y fecha de descarga. Un sorteo es válido solo si la fecha del encabezado se parsea y la cantidad de números coincide con la regla del juego. Para fechas recientes, un vacío puede significar "aún no publicado": reintentar durante unos días antes de confirmar `no_draw`.
3. **Bronce:** HTML/PDF crudo, particionado por país/juego/fecha (solo de sorteos reales). **Plata:** `draws`, `draw_numbers` (formato largo: tipo de bolilla, posición, número como texto con ceros a la izquierda), `prizes`, `draw_timing`, `game_rules` (con vigencia) y `calendar_events` (suspensiones y traslados, con URL de la resolución). **Oro:** métricas y agregados.
4. **Parsers versionados por época** (layout 2007–2015, layout desde 2016-07, extractos HTML y PDF) y un adaptador por juego configurado por YAML.
5. **Validaciones cruzadas:** "Próximo sorteo" contra la siguiente fecha con datos, continuidad de números de sorteo, Tómbola ⊇ últimas dos cifras de Quiniela, el calendario oficial (`ver_calendario.php`) y las estadísticas oficiales (`ver_estadisticas.php`).
6. **Análisis oro:** chi-cuadrado por dígito (centena, decena, unidad), uniformidad de los 1.000 números en total y por posición, tasa de repetidos frente al ~17% esperado, distribución de reemplazos de la Tómbola frente al ~1,8 esperado, frecuencias del 5 de Oro dentro de cada versión de reglas, dinámica de pozos (vacantes, crecimiento, ajuste por inflación) y duración y puntualidad de los sorteos.
7. **Orquestación futura:** backfill único y luego incremental: Quiniela después de ~15:30 y ~21:30 hora de Uruguay, 5 de Oro después de ~22:30 los miércoles y domingos, con revisión del día siguiente por feriados o traslados.
8. **Tests:** fixtures con casos límite: página vacía, fecha `//`, "Sin Aciertos", cupón vacío, artefacto `separador`, `?` por encoding, repetidos en Quiniela, `gif_trasparente`.

# Preguntas abiertas (verificar primero)

Prioriza las que afectan a los tres juegos principales (1, 2, 3, 5, 7 y 8).

1. ¿`ver_resultados.php` muestra el 5 de Oro en el HTML estático en miércoles y domingos, y en todos los años 2007–2026? ¿Con qué campos?
2. ¿Qué devuelve `ver_resultados.php` para una fecha sin sorteo? ¿Cuándo empezaron (si empezaron) los sorteos de Quiniela en fin de semana?
3. ¿Cuál es la fecha más antigua de cada juego principal en `ver_resultados.php` y en `extractosweb`? Las sondas de Quiniela del 02/01/2007 de la sección de URLs sirven para esto: ¿devuelven datos o la plantilla vacía?
4. (Secundaria) ¿Cuál es la ruta del extracto de Lotería Uruguaya y de Kini?
5. Para el PDF: `Content-Type`, `Content-Disposition`, ¿otra URL o la misma? ¿HTML y PDF coinciden siempre (muestra de ~30 fechas entre 2007 y hoy)?
6. (Secundaria) ¿Con qué frecuencia real se sortea la Lotería Uruguaya?
7. Encoding de cada fuente (UTF-8 o ISO-8859-1).
8. Rango válido del 5 de Oro y las versiones de reglas (resoluciones de la DNLQ).
9. Términos de uso y pie legal del sitio.
10. ¿Sirve la página de estadísticas como control cruzado? ¿Tiene datos descargables?

# Tareas

**Fase 0, exploración (ahora):**

- Inspecciona el repo de Santa Lucía y resume sus convenciones reutilizables.
- Escribe scripts desechables para sondear los endpoints con las reglas de cortesía anteriores, empezando por los tres juegos principales. Guarda muestras crudas como fixtures (nunca de las URLs excluidas) y responde las preguntas abiertas.
- Entrega `FINDINGS.md` con evidencia por pregunta: URL, fecha consultada, código de estado, cabeceras relevantes y un fragmento mínimo del contenido.

**Fase 1, diseño (después de revisar Fase 0, esperando mi aprobación):**

- Propón el esquema canónico, el formato YAML por juego, la estrategia de backfill e incremental y el plan de pruebas.
- Lista riesgos y supuestos que Fase 0 no haya podido confirmar.

# Reglas de trabajo

- Distingue siempre entre lo verificado, lo observado y lo hipotético.
- No hardcodees rangos de números ni reglas de juego sin confirmarlos en las resoluciones o en datos.
- Si algo contradice este documento, repórtalo en lugar de ajustarlo en silencio.
- No modifiques el repo de Santa Lucía.
- Cualquier decisión nueva sobre datos personales se pregunta antes de implementarse.
