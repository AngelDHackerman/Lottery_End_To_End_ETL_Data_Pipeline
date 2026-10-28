# FINDINGS — Exploración de las fuentes de Uruguay (Fase 1)

Entregable de la Fase 1 de [`roadmap-uruguay.md`](../../roadmap-uruguay.md). Cada afirmación lleva
una etiqueta:

- **Verificado:** comprobado sobre los datos o con una petición, y se puede repetir.
- **Observado:** visto en una muestra, sin barrer todo el universo.
- **Hipótesis:** explicación plausible que todavía no se confirmó.
- **Informado por el owner:** contexto que aporta Angel. Pasa a *verificado* cuando tiene una
  resolución o una URL citable.

**Evidencia común.** Salvo que se diga otra cosa, todo sale del bronce local y del manifiesto
(`data/uy/manifest.sqlite`) del backfill del **2026-10-04**: 7.370 páginas de `ver_resultados.php`
y 2.072 extractos del 5 de Oro, todas con **HTTP 200** y `Content-Type: text/html; charset=UTF-8`,
descargadas entre las 14:43 y las 20:23 UTC. Los análisis de esta fase se hicieron **sin peticiones
nuevas**. Los cupones se citan solo por su formato (`#########-#`), nunca por su valor. Por la decisión C7 (2026-10-15), los cupones se quedan solo en bronce.

---

## Resumen por pregunta

| Pregunta | Tema | Estado | PR |
|---|---|---|---|
| **Q1** | El 5 de Oro en `ver_resultados` y sus campos | **Respondida** (verificado, campos y valores) | UY-002 |
| **Q2** | Fecha sin sorteo y Quiniela en fin de semana | **Respondida** (verificado; los 4 `error` de 2019 son un paro) | UY-002 |
| **Q3** | Fecha más antigua por juego | **Respondida** (verificado: 2006-08-11 en `ver_resultados` y en los extractos PHP; PDF desde el 2018-11-30) | UY-002 + UY-003 |
| **Q4** | Rutas de Lotería y Kini | **Respondida** (verificado: PDF `…l.pdf` desde 2018-11-30; los PHP de Lotería leen por fecha; el Kini ya está en bronce) | UY-006 |
| **Q5** | PDF frente a HTML | **Respondida** (verificado: el PDF es una impresión del HTML y coincide en el 100% de los campos) | UY-003 |
| **Q6** | Frecuencia de la Lotería | **Respondida** (verificado: viernes; ~42 al año hasta 2012 y 12 al año desde 2014) | UY-006 |
| **Q7** | Encoding | **Respondida** (verificado: UTF-8 en el HTML; el texto de los PDF sale con tildes correctas) | UY-002 + UY-003 |
| **Q8** | Rango y reglas del 5 de Oro | **Respondida** (verificado: 01–44 hasta 2014-03-16, 01–48 desde 2014-03-19; reglas 2012–2026 en CSV; el decreto de 1989 decía 01–36, y lo de 1990–2011 es un hueco) | UY-004 + UY-007 |
| **Q9** | Términos de uso | **Respondida** (no hay términos ni aviso legal; pie y `robots.txt` transcritos, sin conclusión legal) | UY-004 |
| **Q10** | `ver_estadisticas` como control cruzado | **Respondida** (verificado: coincide con el bronce; sin descarga) | UY-004 |
| **—** | Acceso desde AWS | **Respondida** (verificado: us-east-1 llega sin proxy) | UY-005 |

**Cierre (UY-007, 2026-10-15).** Las diez preguntas y la de AWS tienen respuesta. Lo que sigue en
esta sección junta lo que está repartido en el resto del archivo: las decisiones ya tomadas, lo
que se deja para el diseño, los huecos conocidos y las contradicciones con el brief. **Esto es lo
que el owner revisa para el gate G1.**

### Decisiones del owner en la Fase 1

| Fecha | Decisión | Dónde |
|---|---|---|
| 2026-10-06 | Las 13 fechas de Semana de Turismo sin 5 de Oro son **huecos permanentes**, no errores | [Calendario](#miércoles-o-domingos-sin-5-de-oro-y-sin-reemplazo-34-fechas-verificado) |
| 2026-10-14 | **El HTML es la fuente.** El PDF del extracto se baja solo como respaldo | [Q5](#comparación-campo-por-campo-verificado) |
| 2026-10-14 | El **PDF de pozos** se baja siempre, aunque haga falta un proxy: trae el número de sorteo, que el HTML no tiene (era una inclinación; UY-005 la confirmó el 15) | [Q5](#biblioteca-de-pdf-pdfplumber-verificado) |
| 2026-10-15 | Con UY-005 verificado, la nube baja HTML, PDF del extracto y PDF de pozos, **sin proxy** | [UY-005](#uy-005--se-puede-llegar-al-sitio-desde-aws) |
| 2026-10-15 | **Kini: UL2, diferido y solo con backfill.** La Lotería Uruguaya sigue fuera de la v1 (UL1) | [Kini](#kini-verificado) |
| 2026-10-15 | **C7: los números de cupón se quedan solo en bronce.** No entran en plata porque no aportan análisis, pero tampoco se descartan: el bronce guarda la página entera, cupones incluidos | Abajo |
| 2026-10-15 | Las **reglas anteriores a 2012** que no aparezcan se documentan como hueco y **no bloquean G1** | [Q8](#q8--rango-válido-del-5-de-oro-y-versiones-de-las-reglas) |

**Qué implica C7 para el diseño.** Bronce es inmutable, así que nunca se le borran los cupones.
Plata no lleva ninguna columna con números de cupón. La celda del premio sí da un dato que plata
necesita: si hubo ganadores, si fue "Sin Aciertos" o si está vacía (25 celdas, ver
[Q1](#comparación-valor-por-valor)), y eso se guarda como estado del premio. Si plata guarda
además **cuántos** cupones ganaron se decide en UY-010. En este repo los cupones se siguen citando
solo por su formato (`#########-#`).

### Lo que se decide en el diseño (UY-010 / UY-011)

Son propuestas escritas durante la exploración. Ninguna está aprobada todavía:

1. **Datos contaminados:** bronce inmutable, plata conserva el valor publicado con `dq_flags`, el
   vacío se carga como nulo y nunca como cero, y la cuarentena es solo para lo que no se puede
   interpretar ([Q1](#calidad-de-los-datos-de-2006-verificado)).
2. **Los 4 días `error` de 2019:** el clasificador queda estricto y los días pasan a `no_draw` con
   una corrección manual que cita `calendar_events` ([Q2](#los-4-días-error-de-septiembre-de-2019-paro-verificado)).
   Desde UY-007 uno de ellos es fixture (`resultados_2019-09-25.html`) y tiene su test.
3. **Detector de huecos:** el "Próximo sorteo" del sorteo anterior (acierta en el 98,3%) con
   +3 días de tolerancia, más `calendar_events`, porque no hay número de sorteo antes de 2016 (C10, C11).
4. **`game_rules` con vigencias**, sembrado desde [`drafts/game_rules_5_de_oro.csv`](../../src/sorteos/uy/reference/game_rules.csv)
   (el rango depende de la fecha), y **`calendar_events`** desde
   [`drafts/calendar_events.csv`](../../src/sorteos/uy/reference/calendar_events.csv).
5. **pdfplumber** para el PDF de pozos ([Q5](#biblioteca-de-pdf-pdfplumber-verificado)).
6. **El runtime de destino** (C6), antes de escribir un parser: si es Glue 3.9, el guard de
   PR-050 se amplía al paquete nuevo.
7. **Un parser de montos por fuente**, no por época (C12).

### Huecos conocidos (no bloquean G1)

- **El rango 01–44 no tiene resolución.** El Decreto 635/989 creó el 5 de Oro con **01–36**, así
  que entre 1990 y 2006 hubo al menos un cambio que no encontramos ([Q8](#q8--rango-válido-del-5-de-oro-y-versiones-de-las-reglas)).
  Para la v1 basta lo verificado en los datos: 01–44 hasta el 2014-03-16.
- **Precios y porcentajes anteriores a 2012** del 5 de Oro: no están en el sitio.
- **`calendar_events` antes de 2016** casi no tiene eventos. 2006–2015 queda cubierto solo por
  "Próximo sorteo", y 5 eventos de 2014–2015 no tienen URL.
- **Dos domingos de 2006 sin explicar** (2006-08-27 y 2006-08-30). Hipótesis: carga incompleta al
  arrancar el sitio.
- **El paso de la Lotería a mensual en 2013** (hipótesis: una reestructuración junto con el fin del
  Kini). No se buscó la resolución porque la Lotería está fuera de la v1.
- **No se revisaron** `www2.loteria.gub.uy` ni la sección Transparencia (Q9).

### Contradicciones con el brief que verificó la Fase 1

La tabla completa, con su resolución, está en
[`roadmap-uruguay.md`](../../roadmap-uruguay.md#contradicciones-y-huecos-del-brief-resueltos-aquí-o-abiertos).
Estas son las que salieron de los datos:

| # | El brief dice | Lo verificado |
|---|---|---|
| C8 | El sorteo más antiguo es del 07/01/2007 | La historia publicada empieza el **2006-08-11** (el 5 de Oro, el 2006-08-16) |
| C9 | Desde ~2010 algunas URLs bajan un PDF | El PDF aparece el **2018-11-30**, y el PHP sigue respondiendo en todas las fechas |
| C10 | El 5 de Oro se sortea miércoles y domingo | El **12,6%** de los sorteos cae otro día |
| C11 | El número de sorteo sirve de clave y para detectar huecos | No se publica en el HTML; solo en el PDF de pozos, desde 2016 |
| C12 | El HTML de 2016 usa montos en estilo EE.UU. | `ver_resultados` lo usa **desde 2006**; el extracto nunca |
| C13 | El Kini terminó el 31/01/2014 | El último sorteo publicado es el **2013-12-27** (el primero en el sitio, el 2006-08-15) |
| C14 | La Lotería es mensual (dato del owner, no verificado) | **Casi semanal** hasta 2012 (40 a 43 al año) y **mensual desde 2014**, los viernes |
| C15 | Fuentes de terceros dicen 01–48 para el 5 de Oro | **01–44 hasta el 2014-03-16** y 01–48 desde el 2014-03-19. El decreto de 1989 decía 01–36 |

---

## Q1 — ¿El 5 de Oro aparece en `ver_resultados.php`? ¿Con qué campos?

**Pregunta del brief:** ¿`ver_resultados.php` muestra el 5 de Oro en el HTML estático los miércoles
y domingos de todos los años? ¿Con qué campos? Define si la capa 1 (una petición por día) alcanza
para el 5 de Oro o si cada sorteo necesita además su extracto.

### Respuesta

**Sí, en todos los años (verificado).** El bloque del 5 de Oro (imagen `logo_5deoro`, con su
`MostrarExtracto` fechado el mismo día) aparece en **2.072 páginas**, del **2006-08-16** al
**2026-09-30**. Cada una tiene además su extracto en bronce (2.072 y 2.072).

| Año | Sorteos | | Año | Sorteos |
|---|---|---|---|---|
| 2006 (desde el 16/08) | 38 | | 2017 | 102 |
| 2007 | 103 | | 2018 | 104 |
| 2008 | 103 | | 2019 | 102 |
| 2009 | 102 | | 2020 | 104 |
| 2010 | 102 | | 2021 | 104 |
| 2011 | 102 | | 2022 | 102 |
| 2012 | 104 | | 2023 | 105 |
| 2013 | 103 | | 2024 | 104 |
| 2014 | 103 | | 2025 | 105 |
| 2015 | 102 | | 2026 (hasta el 30/09) | 77 |
| 2016 | 101 | | | |

### Campos (verificado en las épocas 2006, 2010, 2016-06, 2016-07 y 2026)

| Campo | `ver_resultados.php` | Extracto `extracto_5_de_oro.php` |
|---|---|---|
| Fecha con día de la semana | `Miércoles 30 de Setiembre de 2026` | `Miércoles 30/09/2026` |
| 5 números + bolilla extra | Seis números; el 6.º es la extra, **sin etiqueta**, separado por `&nbsp;` | Seis números y la etiqueta `Bolilla Extra:` |
| Pozo de Oro y de Plata | `Pozo de Oro: $ 110,629,426.70` (estilo EE.UU.) | `110.629.426,70` (estilo uruguayo) |
| Ganadores | Cupones o `Sin Aciertos` | Cupones (`Cupón Nro:`) o `Sin Aciertos` |
| Revancha | 5 números + `Pozo Revancha` | `SORTEO REVANCHA`, 5 números, `POZO REVANCHA` |
| Próximo sorteo | `Próximo 5 de Oro y Rev.: dd / mm / aaaa` | `Próximo Sorteo: dd / mm / aaaa` |
| **Número de sorteo** | **No está** | **No está** |

Conclusiones:

1. **La capa 1 alcanza para el 5 de Oro (verificado en campos y en valores).** El extracto trae
   los mismos campos y **los mismos valores en los 2.072 sorteos** (ver
   [Comparación valor por valor](#comparación-valor-por-valor)). Queda como control cruzado.
2. **La Revancha existe desde el primer sorteo de la historia** (2006-08-16, verificado).
3. **El formato EE.UU. de montos en `ver_resultados` está desde 2006**, no desde 2016 como suponía
   el brief (verificado). El parser de montos sigue siendo uno por **fuente**, no por época.
4. **El número de sorteo no se publica** ni en `ver_resultados` ni en el extracto. Lo confirmaron
   el barrido y el owner, que tampoco lo encuentra publicado en `loteria.gub.uy`. Solo aparece en
   el PDF de pozos, que existe desde ~julio de 2016. **Consecuencia:** la idea del brief de usarlo
   como clave natural y para detectar huecos no sirve para 2006–2016. Ver la alternativa en
   [Calendario](#calendario-del-5-de-oro).
5. **El bloque "Sorteos para el día de hoy"** (por ejemplo `Domingo 4 de Octubre de 2026 5 de Oro
   Revancha 22:00 hs Canal 12`) aparece en las páginas históricas con la fecha **de la descarga**.
   El parser debe ignorarlo (ya estaba previsto en UY-022).

---

## Calendario del 5 de Oro

### No es solo miércoles y domingo (verificado)

| Día | Sorteos | Nota |
|---|---|---|
| Domingo | 951 | |
| Miércoles | 847 | |
| **Jueves** | **186** | En 42 casos el miércoles no hubo ningún sorteo; en **144** el miércoles sí hubo Quiniela |
| **Lunes** | **75** | En los 75 el domingo no hubo ningún sorteo |
| Viernes | 5 | |
| Sábado | 4 | 2006-12-23, 2006-12-30 y dos en 2023 |
| Martes | 4 | Incluye el 2019-10-01 (ver la huelga de 2019) |

**El 12,6% de los sorteos (261 de 2.072) cae fuera de miércoles o domingo**, y pasa todos los años
de 2006 a 2026.

**Causas (informado por el owner):** feriados, manifestaciones, paros nacionales y **partidos de
fútbol**. El 5 de Oro se transmite en vivo (Canal 12) y se corre cuando la grilla de TV lo pide. Las
resoluciones de cada caso se buscan en UY-004 para pasar estos traslados a `calendar_events`.

### "Próximo sorteo" predice el siguiente (verificado)

La fecha de "Próximo sorteo" de cada sorteo coincide con la del sorteo siguiente en
**2.017 de 2.051 casos (98,3%)**. Hay 20 sorteos sin esa fecha (18 de agosto a octubre de 2006,
más el 2025-02-09 y el 2025-09-14), y 4 la traen con el año en dos dígitos (`03 / 06 / 09`,
`11/ 5 / 22`), que el parser tiene que aceptar. Las 34 diferencias son:

- **Traslados de último momento (31):** se anunciaba el día habitual y se sorteó un día después.
  Por ejemplo, anunciado para el 2013-09-25 y sorteado el 2013-09-26.
- **Un adelanto:** anunciado para el 2012-06-21 (jueves) y sorteado el 2012-06-20 (miércoles).
- **Errores de tipeo en el anuncio (2):** el sorteo del 2009-01-25 anuncia `28/01/2008` (año
  equivocado), y el del 2025-11-12 anuncia `16/12/2025` (mes equivocado, el siguiente fue el
  2025-11-16).

**Consecuencia para el diseño (UY-011 y UY-045):** el sorteo esperado es la fecha que anunció el
sorteo anterior, no "el próximo miércoles o domingo". Si ese día no aparece, se mira hasta 3 días
después antes de alarmar. Esta regla reemplaza al número de sorteo como detector de huecos para
2006–2016.

### Miércoles o domingos sin 5 de Oro y sin reemplazo (34 fechas, verificado)

No hay sorteo de 5 de Oro en ese día ni en los 3 días siguientes:

| Grupo | Fechas | Causa |
|---|---|---|
| **Semana de Turismo (13)** | 2007-04-08, 2008-03-23, 2009-04-12, 2010-04-04, 2011-04-24, 2012-04-08, 2013-03-31, 2014-04-20, 2015-04-05, 2016-03-27, 2017-04-16, 2019-04-21, 2020-04-08 | No se sortea. **Decisión del owner:** son huecos permanentes, no hay forma de recuperarlos y no son un error. |
| **Fin de año (16)** | 2006-12-24, 2006-12-31, 2008-12-31, 2009-12-30, 2010-12-29, 2011-12-28, 2014-12-24, 2015-12-23, 2015-12-30, 2016-12-28, 2017-12-24, 2017-12-31, 2022-12-25, 2022-12-28, 2023-12-24, 2023-12-31 | Navidad, Año Nuevo y la Lotería de fin de año (hipótesis para las fechas que no son feriado). |
| **2019-09-25** | | **Paro de AFAL, el gremio de la DNLQ** (informado por el owner, confirmado en [prensa](https://focusgn.com/latinoamerica/loterias-uruguayas-apuestas) y en los OIS 2036 y 2037 de la DNLQ): rechazo a eliminar a los "niños cantores" de las extracciones. Ese 5 de Oro se sorteó el **martes 2019-10-01**. Coincide con los 4 días `error` (25, 26, 27 y 30 de septiembre), en los que tampoco hubo Quiniela. Detalle en [Q2](#los-4-días-error-de-septiembre-de-2019-paro-verificado). |
| **2026-01-21** | | **Cambio de calendario de la DNLQ** (informado por el owner): para no superponerse con el sorteo extraordinario "La Revancha de Reyes" del viernes 2026-01-23, las apuestas pasaron al domingo 2026-01-25. El manifiesto lo confirma: el 23 trae un bloque `loteria` y el 25 trae el 5 de Oro. |
| **2016-04-17** | | **Duelo Oficial nacional** (informado por el owner) decretado por el Poder Ejecutivo tras el tornado F3 de Dolores (Soriano) del 2016-04-15. Durante un duelo oficial, la DNLQ suspende la comercialización y los sorteos públicos. El sorteo anterior lo había anunciado y el siguiente fue el 2016-04-20. |
| **Sin explicar (2)** | 2006-08-27, 2006-08-30 | Caen en las dos primeras semanas de la historia publicada. Hipótesis: carga incompleta al arrancar el sitio. Esos mismos sorteos tampoco anuncian el próximo, así que no hay forma de confirmarlo con los datos. |

La causa de las páginas `error` de septiembre de 2019 ya está explicada en
[Q2](#los-4-días-error-de-septiembre-de-2019-paro-verificado).

---

## Calidad de los datos de 2006 (verificado)

Los primeros meses parecen cargados a mano:

| Caso | `ver_resultados` | Extracto | Lectura |
|---|---|---|---|
| 2006-08-20, pozos de Oro y de Plata | `$` sin monto | `0,00` y `0,00` | Falta el dato. `0,00` es el marcador de plantilla vacía y **no** es un pozo de cero. |
| 2006-12-06, Pozo de Plata | `12,022,391.73` | `12.022.391,73` | Es igual al Pozo de Oro. Es casi seguro un error de tipeo. |
| "Sin Aciertos" | `sin aciertos`, `Sin Acierto`, `sin acierto`, `SIN ACIERTO`, `Sin Aciertos` | | Se normaliza sin distinguir mayúsculas y aceptando singular y plural. |
| Cupones | `#########-#`, `########-#`, `########-#-#`, `##########-#-#`, `###########-#` | | Además, en 2026 hay cupones de 10 dígitos sin guion. Es esperable en 20 años de mantenimiento del sitio. |

**Las dos fuentes comparten el error** (verificado en los dos casos de pozos). Salen de la misma base
de datos, así que la comparación entre fuentes **no** corrige tipeos: solo detecta errores de
parseo nuestros.

**Propuesta para los datos contaminados** (se decide en UY-010):

1. **Bronce es inmutable.** El HTML se guarda tal cual vino.
2. **Plata conserva el valor publicado**, sin corregirlo, y agrega una columna `dq_flags` (lista)
   con lo que detectan las validaciones: `pozo_missing`, `pozo_plata_equals_oro`,
   `next_draw_announcement_mismatch`, etc. Así el dato es fiel a la fuente y el problema queda
   visible.
3. **El marcador de vacío (`0,00` o `$` sin monto) se carga como nulo**, nunca como cero.
4. **La cuarentena es solo para filas que no se pueden interpretar**: números fuera de rango,
   cantidad equivocada de bolillas, fecha que no coincide. Un pozo sospechoso no va a cuarentena.
5. **Oro filtra por flag según la métrica.** La dinámica de pozos excluye las filas con flags de
   pozo. Las frecuencias de números las usan igual, porque el tipeo está en el monto y no en las
   bolillas.
6. **Correcciones solo con fuente.** Si algún día aparece el valor correcto (PDF de pozos, prensa),
   va a una tabla aparte de correcciones con su URL. Nunca se sobrescribe el valor publicado.

---

## Comparación valor por valor

**Método.** Un script desechable de la Fase 1, sin red, lee los 2 × 2.072 archivos del bronce. Hay
dos parsers independientes, uno por fuente:

- `ver_resultados` se lee por las imágenes de las bolillas (`circulo_oro.gif`,
  `circulo_oro_ext.gif`), las etiquetas `Pozo de …: $` y la celda que sigue a cada pozo.
- El extracto se lee por las clases CSS (`Estilo_aproximaciones_nro`, `Estilo_fecha`) y la tabla
  de `Cupón Nro:`.

Los montos se pasan a `Decimal` con el formato de cada fuente. El marcador vacío (`$` sin monto o
`0,00`) se carga como nulo. "Sin Aciertos" se reconoce sin distinguir mayúsculas y en singular o
plural. Los cupones se comparan en memoria y el reporte solo dice si coinciden, nunca su valor.
Tarda unos 19 s.

**Resultado (verificado): las dos fuentes coinciden en el 100% de los valores.**

| Campo | Iguales | Vacíos en las dos | Distintos | Falta en una | No parsea |
|---|---|---|---|---|---|
| Fecha | 2.072 | 0 | 0 | 0 | 0 |
| 5 números | 2.072 | 0 | 0 | 0 | 0 |
| Bolilla extra | 2.072 | 0 | 0 | 0 | 0 |
| Pozo de Oro | 2.071 | 1 (2006-08-20) | 0 | 0 | 0 |
| Pozo de Plata | 2.071 | 1 (2006-08-20) | 0 | 0 | 0 |
| Ganadores Oro | 2.072 | — | 0 | 0 | 0 |
| Ganadores Plata | 2.072 | — | 0 | 0 | 0 |
| Revancha (5 números) | 2.072 | 0 | 0 | 0 | 0 |
| Pozo Revancha | 2.071 | 1 (2006-08-20) | 0 | 0 | 0 |
| Ganadores Revancha | 2.072 | — | 0 | 0 | 0 |
| Próximo sorteo | 2.052 | 20 | 0 | 0 | 0 |

Los cupones coinciden carácter por carácter, sin necesidad de normalizarlos. Los errores de tipeo
también coinciden (el Pozo de Plata igual al de Oro el 2006-12-06, y los anuncios con año o mes
equivocado). Esto confirma que las dos páginas salen de la misma base.

**Controles de forma sobre los 2.072 sorteos (verificado):**

- Siempre hay **5 números distintos** en el 5 de Oro y otros 5 en la Revancha.
- La **bolilla extra nunca repite** uno de los 5 números.
- Los 5 números se publican **siempre en orden ascendente**, en las dos fuentes. **Consecuencia
  para el análisis (UY-032):** el orden de extracción no se publica, así que en el 5 de Oro no se
  puede analizar la frecuencia **por posición**, solo por número. En la Quiniela sí se puede,
  porque sus 20 posiciones están numeradas.
- **Rango: 01–44 hasta el 2014-03-16 y 01–48 desde el 2014-03-19** (corregido en UY-004). Aquí
  decía "01 a 48 en las dos épocas (2006–2016 y 2016–2026)": era cierto para esos dos bloques,
  pero escondía el cambio de reglas de la As. 176/2014. Ver
  [Q8](#q8--rango-válido-del-5-de-oro-y-versiones-de-las-reglas).

**Ganadores: "Vacío" es distinto de "Sin Aciertos" (verificado).** En `ver_resultados` hay:

| Premio | Cupones | Sin Aciertos | Vacío |
|---|---|---|---|
| Oro | 543 | 1.518 | 11 |
| Plata | 1.445 | 621 | 6 |
| Revancha | 509 | 1.555 | 8 |

Las 25 celdas vacías (6 en los dos primeros sorteos de 2006 y el resto repartido entre 2006 y 2026)
están vacías también en el extracto. Hipótesis: el dato no se cargó. En plata deben quedar como
"desconocido", no como "Sin Aciertos" ni como "con ganadores".

> **Corregido en UY-022 (verificado con el parser sobre las 2.077 páginas del 5 de Oro):** las
> vacías de verdad son **11** (Oro 4, Plata 4, Revancha 3: 2006-08-16, 2006-08-20, 2006-10-29,
> 2007-01-17, 2014-06-08, 2023-05-21 y 2023-11-12). Las otras 14 sí dicen algo y el script de Q1
> no las reconoció: 12 grafías de "Sin Aciertos" (`Sin Acierrtos`, `Sin Aiciertos`,
> `SinAciertos`, `si aciertos`…) y 2 "Vacante" (2014-05-11, Oro y Revancha).

## Pendiente de Q1

- ~~Sumar los traslados de fecha a `calendar_events` con su resolución (UY-004).~~ Hecho en
  UY-004 para 2016–2026: ver [Calendario oficial](#calendario-oficial-y-calendar_events). Antes
  de 2016 casi no hay resoluciones publicadas.

---

## Q2 — ¿Qué devuelve una fecha sin sorteo? ¿Desde cuándo hay Quiniela en fin de semana?

**Pregunta del brief:** cómo se ve un día sin sorteo (para no confundirlo con una falla) y desde
cuándo se sortea Quiniela los sábados y domingos (para saber qué días esperar datos).

### Fecha sin sorteo (verificado)

- **HTTP 200**, `text/html; charset=UTF-8` y la misma plantilla de siempre, pero **sin bloques de
  juego**: ni llamadas a `MostrarExtracto(...)` ni imágenes de cabecera. Pesa entre 45,8 y 48,0 KB,
  y una página con sorteo pesa 53,7 KB o más. El tamaño orienta, pero la regla es el contenido. Fixture: `resultados_2025-12-25.html`.
- El sitio **nunca** avisa con un código de estado. La única señal es el contenido, y es la regla de
  `classify.py` (plantilla sin bloques → `no_draw`).
- **Una página vacía no distingue "no hubo sorteo" de "todavía no se publicó".** El 2026-10-04
  (domingo, 5 de Oro a las 22:00) se pidió a las 17:23 hora de Uruguay y llegó vacía, igual que un
  feriado. Por eso `not_yet_published` sale de la **hora de la petición** y no de la página.
- **457 de los 7.370 días** del backfill son `no_draw`: 10 son anteriores al primer día con datos
  (2006-08-01 a 2006-08-10, ver [Q3](#q3--fecha-más-antigua-de-cada-juego))
  y 447 caen dentro de la historia.

Los feriados fijos que se repiten casi todos los años de 2006 a 2026:

| Fecha | Años sin sorteo | Feriado |
|---|---|---|
| 01/01 | 20 | Año Nuevo |
| 06/01 | 19 | Reyes |
| 01/05 | 20 | Día de los Trabajadores |
| 19/06 | 20 | Natalicio de Artigas |
| 18/07 | 20 | Jura de la Constitución |
| 25/08 | 21 | Declaratoria de la Independencia |
| 02/11 | 19 | Difuntos |
| 25/12 | 20 | Navidad |

El **24 y el 31 de diciembre** no tienen sorteo en 10 años cada uno. Los otros años suele haber
**solo la Vespertina**: de las 17 páginas de toda la historia cuyo único juego es la Vespertina,
13 son un 24 o un 31 de diciembre (observado).

### Quiniela en fin de semana (verificado)

**El calendario semanal no cambió en 20 años.** No hay una fecha de inicio que buscar, así que la
bisección prevista (~12 peticiones) no hace falta:

| Día | Días desde 2006-08-11 | Vespertina + Nocturna | Solo Nocturna | Solo Vespertina | Sin sorteo |
|---|---|---|---|---|---|
| Lunes a viernes | 5.256 | 4.922 | 16 | 21 | 292 |
| **Sábado** | 1.052 | 0 | **997** | 0 | 55 |
| **Domingo** | 1.052 | 0 | 0 | 0 | 100 (+951 con solo 5 de Oro) |

- **Sábado:** Quiniela **Nocturna** desde el primer sábado de la historia (2006-08-12), todos los
  años. La Vespertina **nunca** se sorteó un sábado.
- **Domingo:** **nunca** hubo Quiniela. El domingo es solo del 5 de Oro.
- De lunes a viernes faltan en la tabla los 4 días `error` (el paro de 2019, ver abajo) y un
  miércoles con otro juego y sin Quiniela.

**Consecuencia para el diseño (UY-011):** el calendario esperado de la Quiniela es V+N de lunes a
viernes, N los sábados y nada los domingos. Los días con una sola de las dos (37 de lunes a viernes)
son excepciones que el detector de huecos tiene que tolerar, no alarmas.

### Los 4 días `error` de septiembre de 2019 (paro, verificado)

**Causa: un paro de AFAL**, la asociación de funcionarios de la DNLQ, contra la eliminación de la
figura del "niño cantor" en las extracciones (informado por el owner). **La DNLQ lo confirma
oficialmente** en el [OIS 2036](https://www.loteria.gub.uy/Comunicados/2019/OIS_2036_%5B25_09_2019%5D.pdf)
("paro parcial dispuesto por A.F.A.L. desde las 13:30 hasta las 23:59", con el 5 de Oro
trasladado al jueves 26) y en el
[OIS 2037](https://www.loteria.gub.uy/Comunicados/2019/OIS_2037_%5B26_09_2019%5D.jpg) (paro desde
las 14:00 del 26, con el 5 de Oro pasado al viernes 27). El motivo del niño cantor no figura en los
OIS. Lo confirma una nota de
[FocusGN del 2019-10-03](https://focusgn.com/latinoamerica/loterias-uruguayas-apuestas): el gremio
"había decretado un paro desde la semana pasada", lo levantó tras reunirse con la DNLQ y el
Ministerio de Trabajo, y la figura se mantuvo hasta el 31 de diciembre de 2019.

Lo que muestra el manifiesto:

| Fecha | Día | Estado | Página |
|---|---|---|---|
| 2019-09-24 | martes | `draw` | Quiniela V+N, el último día normal |
| 2019-09-25 a 27 | miércoles a viernes | `error` | 48.072 bytes cada una: hay cabeceras de juego pero ningún `MostrarExtracto` |
| 2019-09-28 y 29 | sábado y domingo | `no_draw` | Plantilla vacía |
| 2019-09-30 | lunes | `error` | Igual que el 25 |
| 2019-10-01 | martes | `draw` | Nocturna + el 5 de Oro del domingo 29 |

- **El clasificador hizo lo que tenía que hacer.** Un bloque de juego sin código es una página que
  no se entiende, y `classify.py` la marca como `error` en vez de adivinar.
- **Contradicción con la prensa:** la nota dice que se volvió a sortear con el 5 de Oro del
  "2 de octubre". El sitio oficial lo publica el **2019-10-01** en `ver_resultados` y en la cabecera
  del extracto. Manda la fuente oficial.
- **No es el único paro.** El miércoles **2017-08-09** hubo otro, también de los funcionarios
  ([FocusGN, 2017-08-09](https://focusgn.com/latinoamerica/paro-loterias-quinielas-uruguay): "no
  habrá sorteo de quinielas, Tómbola y 5 de Oro"). Ese día sale como `no_draw` con plantilla vacía,
  y el 5 de Oro pasó al jueves 2017-08-10. **Un paro no siempre se ve igual en la página.**
  UY-004 encontró más paros con resolución oficial (2017, 2021 y 2024): ver
  [Calendario oficial](#calendario-oficial-y-calendar_events).

**Propuesta (se decide en UY-010 / UY-011):** el clasificador queda estricto. Los 4 días se pasan a
`no_draw` con una corrección manual en el manifiesto, que cita una fila de `calendar_events`
(causa `paro`, con la URL de la nota). Un `error` nuevo sigue pidiendo revisión humana.

**Fixture (UY-007, verificado):** las 4 páginas no quedaron en bronce, porque bronce solo guarda
sorteos, así que se volvió a pedir la del 2019-09-25 (1 petición, 2026-10-16 01:26 UTC, HTTP 200).
Sigue clasificando como `error` ("game blocks without extract codes"): muestra la cabecera de la
Vespertina y ningún `MostrarExtracto` con código. Pesa 48.803 bytes contra los 48.072 del backfill,
por el bloque "Sorteos para el día de hoy". Quedó en `tests/fixtures/uy/resultados_2019-09-25.html`,
con un test que la clasifica.

---

## Q3 — Fecha más antigua de cada juego

**Respuesta (verificado):** la historia empieza el **2006-08-11**, no el 07/01/2007 que daba el brief
(ver C8 en el roadmap). Del 2006-08-01 al 2006-08-10 la página sale vacía.

### Parte `ver_resultados` (UY-002)

| Juego | Primer día | Último día en el backfill | Páginas |
|---|---|---|---|
| Lotería | 2006-08-11 | 2026-09-18 | 421 |
| Quiniela Nocturna | 2006-08-11 | 2026-10-03 | 5.935 |
| Kini | 2006-08-15 | **2013-12-27** | 1.793 |
| Quiniela Vespertina | 2006-08-16 | 2026-10-02 | 4.943 |
| 5 de Oro | 2006-08-16 | 2026-09-30 | 2.072 |

- **El Kini no aparece después de 2013-12-27** (verificado en `ver_resultados`). Ver
  [Q4 y Q6](#q4-y-q6--lotería-uruguaya-y-kini).
- **Códigos de Lotería que `sources.py` no conoce (verificado):** 15 páginas, del 2018-12-29 al
  2023-01-20, traen códigos `MostrarExtracto` del **27 al 38**. `game_for_code` solo reconoce como
  Lotería el 1 y del 6 al 26, así que quedan como `unknown_27` … `unknown_38`. Caen siempre a fin de
  diciembre o entre el 15 y el 24 de enero. Hipótesis: sorteos extraordinarios de Lotería (fin de
  año y Reyes), con un código nuevo cada año. Se resuelve con las rutas de Lotería en UY-006 (Q4).
  **Resuelto en UY-006:** ver [Q4 y Q6](#q4-y-q6--lotería-uruguaya-y-kini).

### Parte `extractosweb` (UY-003, verificado)

- **Los extractos PHP empiezan el mismo día que `ver_resultados`.** Los 15 sondeos anteriores al
  2006-08-11 (2005-08-14, 2006-01-04, 2006-07-16, 2006-08-09 y 2006-08-10, en los tres juegos)
  devuelven la plantilla vacía, byte a byte igual a la de cualquier día sin sorteo.
- **El extracto PHP nunca falta.** En los 12.950 días en que `ver_resultados` lista uno de los tres
  juegos, su extracto PHP trae datos con la fecha correcta. No hay ni un `missing`.
- **El PDF existe desde el 2018-11-30**, la fecha en que `MostrarExtracto()` empieza a enlazarlo (C9).
  Hay archivos sueltos de octubre de 2018 en la misma ruta, pero son pruebas y no sirven (ver
  [Q5](#pdfs-anteriores-al-2018-11-30-verificado)).

---

## Q5 — ¿El PDF es la misma fuente que el HTML?

**Pregunta del brief:** qué devuelve el PDF del extracto (`Content-Type`, `Content-Disposition`,
redirecciones) y si dice lo mismo que el extracto HTML, comparando unas 30 fechas por juego.

**Respuesta (verificado): sí. El PDF es una impresión del extracto HTML que alguien hace a mano
desde un navegador, y coincide con el HTML en el 100% de los campos.** No aporta ningún dato
que el extracto PHP no tenga.

**Evidencia.** Un backfill acotado de la fuente `pdf` (226 peticiones el 2026-10-14, a 1 req/s,
con el cliente de UY-001) sobre unas 4 fechas al azar por año y juego de 2018 a 2026, más el
primer día de cada juego. Como el backfill pide los tres juegos de cada fecha, quedaron 245 PDF en
bronce, contando los 21 del piloto de septiembre de 2025. Se agregan 34 peticiones de bisección
para buscar el inicio y las sondas del día.

### Qué es el PDF (verificado)

- **Lo genera un navegador, no un sistema.** El `Creator` de los 245 PDF es Chrome (versiones 70 a
  109, en Windows, `Skia/PDF`) desde 2018 y Firefox (versiones 141 a 157, `cairo`) desde septiembre
  de 2025.
- **Es una impresión de la página PHP.** En 41 PDF (2018, 2019 y 2023) quedó impresa la cabecera
  del navegador, con la URL de la página (`…/extracto_5_de_oro.php?vdia=02&vmes=12&vano=2018`) y
  la paginación `1/1`.
- **Se imprime la noche del sorteo.** La `CreationDate` cae el mismo día o el siguiente. Es una foto
  del extracto en el momento de publicarlo. En cambio, el HTML se regenera desde la base en cada
  petición, así que compararlos también dice si la base cambió después de publicar. No cambió.
- Siempre tiene una sola página.

### Cabeceras y disponibilidad (verificado)

- `Content-Type: application/pdf`, **sin `Content-Disposition`** y **sin redirecciones**: la URL
  pedida es la final en todas las respuestas.
- Si no existe, responde **404** con un `text/html` de 146 bytes.
- Trae `Last-Modified`, que el extracto PHP no tiene. Pero los 52 PDF del 2018-11-30 al 2021-06-24
  dicen todos `Thu, 22 Jul 2021 18:44:04 GMT`, señal de una migración de archivos. Antes de
  mediados de 2021 no sirve como hora de publicación.
- **El PDF tiene huecos y el PHP no.** Hay 2 sorteos sin PDF (404) que sí tienen extracto PHP: el
  5 de Oro del **2019-01-07** (lunes, trasladado) y la Nocturna del **2022-06-01**. Ese mismo
  2022-06-01, los PDF del 5 de Oro y de la Vespertina son **imágenes sin texto**: su `Creator` es
  `Adobe Fireworks CS5` en uno y un firmware de tablet Samsung (`T835XXU5CUE2`) en el otro.
  Hipótesis: ese día no estaba el equipo de siempre.

### Comparación campo por campo (verificado)

**Método.** Es un script desechable sin red. Lee el texto de cada PDF con pdfplumber y el de su
extracto PHP con BeautifulSoup, y pasa los dos por **el mismo** extractor de campos. Los cupones se
comparan en memoria y no se imprimen.

**Resultado: en los 243 PDF con texto desde el 2018-11-30, todos los campos son iguales.**

| Juego | PDF | Campos comparados | Distintos |
|---|---|---|---|
| 5 de Oro | 51 | Fecha, 5 números + extra, pozos de Oro, Plata y Revancha, ganadores (cupones y "Sin Aciertos"), números de la Revancha, próximo sorteo | 0 |
| Quiniela Nocturna | 100 | Fecha, los 20 números de 3 cifras **en su orden**, horas de inicio, primero y fin, los 20 de 2 cifras, próximo sorteo | 0 |
| Quiniela Vespertina | 92 | Los mismos | 0 |

La única diferencia es de formato y no de dato: el próximo sorteo de la Nocturna del 2021-08-26
dice `27/8/2021` en el PDF y `27/08/2021` en el HTML.

**Decisión del owner (2026-10-14): el HTML es la fuente, y el PDF se baja como respaldo
solo si no hace falta un proxy.**

- **Plata sale siempre del HTML** (`ver_resultados` y los extractos PHP). El PDF no se parsea.
- **Sin proxy** (si UY-005 confirma que AWS llega directo al sitio): se descargan el HTML y el PDF.
  El PDF va a bronce como copia de la publicación de esa noche.
- **Con proxy** (como Santa Lucía): solo el HTML. Cada petición cuesta créditos, y el PDF
  duplicaría el costo sin aportar ningún dato.
- **El PDF que falta no alarma.** Tiene huecos que el HTML no tiene (los 404 y las imágenes de
  arriba), así que un PDF `missing` queda registrado en el manifiesto pero no dispara alertas. Lo
  que alarma es que falte el HTML.
- **Costo de guardarlo:** unos 300 KB por PDF frente a unos 15 KB por extracto HTML. Con 651
  extractos al año (2025) son ~190 MB por año, menos de un centavo al mes en S3.
- **Histórico:** no hace falta bajar los ~4.800 PDF que faltan desde el 2018-11-30 (~1,4 h a
  1 req/s, ~1,4 GB). Si algún día se quieren, la fuente `pdf` del backfill ya los baja.

### PDFs anteriores al 2018-11-30 (verificado)

En la misma ruta hay archivos de **octubre de 2018**, antes de que el sitio los enlazara. La
bisección encontró el primero el 2018-10-09 (Vespertina), el 2018-10-26 (Nocturna) y el 2018-10-28
(5 de Oro), con huecos en medio (la Vespertina del 2018-10-10 no existe). En junio de 2017 no hay
ninguno.

**No sirven.** De los 7 que se bajaron, 5 no corresponden a su fecha:

- `20181009v.pdf` trae el extracto del **23/10/2018**.
- `20181026v.pdf`, `20181026n.pdf`, `20181027n.pdf` y `20181028o.pdf` dicen **29/10/2018** y no
  traen números. Parecen pruebas de la plantilla.

Solo los del 5 de Oro del 2018-10-31 y del 2018-11-11 coinciden con el HTML. **El inicio válido
del PDF es el 2018-11-30 (C9).**

### Plantilla vacía y `no_draw` (verificado)

| Fuente | Cómo se ve vacía | Tamaño |
|---|---|---|
| Extracto PHP del 5 de Oro | Fecha `//`, pozos `0,00`, sin bolillas | 11.519 bytes |
| **Extracto PHP de la Quiniela** | **Otra plantilla:** sin fecha ni pozos, solo la imagen `extracto_sin_info.gif` | 719 (V) y 777 (N) bytes |
| PDF | 404 | 146 bytes |

Las plantillas vacías son idénticas byte a byte en todas las fechas probadas.

**Una página vacía no dice por qué está vacía.** La misma plantilla sale antes de 2006, en un día
sin sorteo y en un sorteo que todavía no se publicó (verificado el 2026-10-14, abajo). Pasa igual
en el HTML y en el PDF.

**Bug en `classify.py` (verificado):** `classify_extracto_php` busca la fecha o el `//`, así que la
plantilla vacía de la Quiniela sale como `error` ("no header date and no empty-template marker")
en lugar de vacía. El backfill no lo vio porque solo pide un extracto cuando `ver_resultados` lista
el juego, y ninguno vino vacío. **En la ingesta diaria, una Quiniela todavía no publicada saldría
como `error`.** Arreglo: reconocer `extracto_sin_info.gif` como marcador de vacío, con su fixture y
su test, en un PR de código aparte.

### `not_yet_published`: cuándo se publica (verificado)

**Sondeo del 2026-10-14 (miércoles).** Las fuentes de cada sorteo se pidieron cada 10 minutos
hasta que aparecieron (3 peticiones por ronda). El 5 de Oro no se sorteó ese día: el calendario
oficial lo había pasado al jueves 15 (ver UY-004), así que el sondeo solo siguió a la Nocturna.

| Sorteo | Fin del sorteo | HTML (`ver_resultados` y extracto PHP) | PDF (`Last-Modified`) |
|---|---|---|---|
| Vespertina | 15:19 | Ya estaba a las 18:46 (primer sondeo) | 15:29:14, **10 min** después del fin |
| Nocturna | 21:20 | Vacío a las 21:23:35 y publicado a las 21:33:36: **entre 3 y 13 min** después del fin | 21:33:44, **14 min** después del fin. A las 21:33:38 todavía daba 404 |

- **Antes de publicarse, la página es idéntica a la de un día sin sorteo:** el extracto PHP es la
  plantilla vacía de 777 bytes, el PDF da 404 y `ver_resultados` no trae el bloque del juego.
  Solo la hora distingue "todavía no" de "no hubo".
- **El HTML sale antes que el PDF.** Es lo esperable, porque el PDF es una impresión que alguien
  sube después.
- Los PDF del día coinciden con su HTML en todos los campos.

**Consecuencia para la ingesta diaria (UY-043):** una corrida a las ~23:30 hora de Uruguay ya
encuentra la Quiniela y el 5 de Oro del día. Lo que falte se marca `not_yet_published` y se vuelve a
pedir al día siguiente, como en `settle_days`. Se pasa a `no_draw` solo después de ese plazo y si
el calendario esperado tampoco lo anunciaba.

**Demora histórica entre el fin del sorteo y el `Last-Modified` del PDF** (2020–2026, sin los
archivos migrados):

| Juego | PDF | Mediana | p90 | Máximo |
|---|---|---|---|---|
| Quiniela Vespertina | 73 | 9 min | 14 min | 84 min |
| Quiniela Nocturna | 78 | 9 min | 16 min | 74 min |
| 5 de Oro | 42 | 42 min | 53 min | — |

Para la Quiniela se mide desde la hora de "Fin" del propio extracto. El 5 de Oro no publica la
hora, así que se mide desde las 22:00 nominales. Los extremos son sorteos que se corrieron a otra
hora.

### PDF de pozos del 5 de Oro (verificado)

- **Este sí lo genera un sistema:** `JasperReports (reporteInformacionDePozos)` con iText. Se emite
  **antes** del sorteo (por ejemplo, a las 21:07 para el de las 22:00).
- **Trae el número de sorteo**, la única fuente que lo tiene: 1856, 1857, 1858 y 1859 en los
  4 sorteos de julio de 2016 que hay en bronce, consecutivos.
- Sus tres montos son iguales a los pozos del extracto en los 4 casos.

### Biblioteca de PDF: pdfplumber (verificado)

| | pdfplumber 0.11 | pypdf 6.20 |
|---|---|---|
| Extractos (243 PDF) | 243 bien | **Falla en los 51 del 5 de Oro**: pega la bolilla extra a la etiqueta (`41Bolilla`) |
| PDF de pozos | Cada etiqueta en su línea con su monto | Separa las etiquetas de los montos en bloques |
| Tiempo para unos 250 PDF | 7,9 s | 3,4 s |

**Propuesta:** pdfplumber. La velocidad no importa con unos pocos PDF por día. Como los extractos
salen del HTML, solo haría falta para el PDF de pozos. El PDF de pozos no es un respaldo, porque trae
el único dato que el HTML no tiene (el número de sorteo). **Inclinación del owner (2026-10-14):**
bajarlo aunque haga falta un proxy, porque es una fuente distinta y no una impresión del HTML. Son
~104 peticiones al año, y está enlazado en 1.055 de los 2.072 sorteos (desde el 2016-06-01). Se
confirma en UY-010, con el resultado de UY-005.

---

## Q7 — Encoding

**Respuesta (verificado): todo es UTF-8 y no hay que adivinar nada.**

### HTML (UY-002)

- Las **20.320 respuestas HTML** del backfill (7.370 de `ver_resultados` y 12.950 extractos PHP)
  traen la cabecera `Content-Type: text/html; charset=UTF-8`. Los 25 PDF traen `application/pdf`.
- Los **19.858 archivos HTML de bronce** decodifican como UTF-8 estricto sin un solo error, no
  tienen BOM y declaran `<meta charset=utf-8>`. No aparece mojibake (`Ã©`, `Â`) en ninguno.
- **El único carácter roto es `Pe?aloza`**, en el pie de firma de los extractos: 2.083 archivos de
  2006 a 2022, nunca escrito bien. En los bytes es un `?` literal (0x3F), así que la `ñ` se perdió
  en el origen cuando se cargó el dato y no se puede recuperar decodificando de otra forma. El
  parser no lee el pie, así que no afecta a ningún campo.
- Las 462 páginas que no quedaron en bronce (`no_draw`, `error` y `not_yet_published`) solo se
  verificaron por la cabecera.

**Consecuencia para los parsers (UY-022 a UY-024):** decodificar con `utf-8` estricto y fallar si algo no
decodifica. Hoy `classify.py` usa `errors="replace"`, que sirve para clasificar pero escondería un
cambio de encoding en plata.

### PDF (UY-003, verificado)

El texto que extrae pdfplumber de los 243 PDF con texto trae las tildes y la `ñ` bien (`Próximo`,
`NÚMEROS`, `Miércoles`, `Cupón`, `Sábado`). No aparece ni un `?` ni un carácter de reemplazo
(U+FFFD) fuera de las URLs. El PDF de pozos también sale limpio (`INFORMACIÓN DE POZOS`).

---

## Q8 — Rango válido del 5 de Oro y versiones de las reglas

**Pregunta del brief:** el rango válido de números del 5 de Oro (las fuentes de terceros decían
01–48) y cómo cambiaron las reglas con los años, para armar `game_rules` con vigencias.

**Respuesta (verificado): el rango cambió el 2014-03-19. Antes era 01–44 y desde entonces es
01–48.** Lo fija la As. 176/2014: "cinco (5) números entre 01 al 48 inclusive", a partir del sorteo
del 19 de marzo de 2014. Los datos lo confirman:

| Período | Sorteos | Mínimo | Máximo |
|---|---|---|---|
| 2006-08-16 a 2014-03-16 | 779 | 01 | **44** |
| 2014-03-19 a 2026-09-30 | 1.293 | 01 | **48** |

- En los 779 sorteos anteriores, ningún número del 5 de Oro, la extra o la Revancha pasa de 44.
- El primer sorteo con las reglas nuevas (2014-03-19) ya trae un 45 y un 48.
- Desde entonces, del 45 al 48 salieron entre 262 y 323 veces cada uno.
- No encontramos la resolución que fijó el 01–44: sale de los datos.

**Esto corrige a Q1**, que decía "rango observado de 01 a 48 en las dos épocas (2006–2016 y
2016–2026)". Era cierto para esos dos bloques, pero escondía el cambio de 2014.

**Consecuencia para las validaciones (UY-025):** el rango depende de la fecha del sorteo. Un 45
antes del 2014-03-19 es un error de datos, no un número válido. Por eso `game_rules` lleva
vigencias.

### Las resoluciones del 5 de Oro (verificado, leídas)

La página del juego (`Juego_Quiniela.php?xjue=4&xpos=1`) enlaza 4 resoluciones, y `noticias.php`
otras 4. Todas son **escaneos sin texto**, así que se leyeron como imagen:

| Vigencia | Resolución | 5 de Oro | Revancha | Pozo de Oro | Dividendos fijos (4/5 · 3/5+E · 3/5 · 2/5+E · 2/5) |
|---|---|---|---|---|---|
| 2012-02-01 | Del 23/01/2012 (citada; no está publicada) | $ 25 | $ 10 | — | — |
| 2012-03-04 | As. 144/2012 | — | $ 15 (pozo 45,47%) | — | — |
| **2014-03-19** | **As. 176/2014** (rango 01–48) | $ 20 | $ 10 (pozo 55%) | 31,47% | 4.000 · 800 · 200 · 80 · 30 |
| 2019-01-07 | Res. 923/2018 (corrige la 920/2018) | $ 30 | $ 10 | 32,59% | 6.000 · 1.200 · 300 · 120 · 40 |
| 2020-01-02 | Res. 1334/2019 | $ 35 | $ 15 | 31,95% | 7.000 · 1.400 · 350 · 140 · 50 |
| 2022-10-16 | Res. 519/2022 | $ 40 | $ 20 | 31,47% | 8.000 · 1.600 · 400 · 160 · 60 |
| 2025-09-17 | Res. 147/2025 | $ 45 | $ 20 | 31,84% | 9.000 · 1.800 · 450 · 180 · 65 |
| 2026-01-04 | Res. 222/2025 y 222(1)/2025 | $ 50 | $ 20 | 32,14% | 10.000 · 2.000 · 500 · 200 · 70 |

El Pozo de Plata es 3% en todas las versiones desde 2014, y el Pozo Revancha 55%.

- **Las vigencias caen en sorteos reales.** Dos son traslados: el lunes 2019-01-07 (del domingo 6,
  Reyes) y el jueves 2020-01-02 (del miércoles 1, Año Nuevo). La excepción es la Res. 519/2022,
  que rige "a partir del sorteo del día 16 de octubre de 2022": ese domingo no hubo sorteo, y el
  primero con los valores nuevos fue el lunes 2022-10-17. Ese traslado no figura en las noticias.
- **Las resoluciones se corrigen entre sí.** La 923/2018 corrige "la fecha de vigencia, el monto del
  premio 2/5 y el porcentaje del Pozo de Oro" de la 920/2018. La 222(1)/2025 cambia el Pozo de Oro
  de 31,84% a 32,14%. `game_rules` tiene que citar la versión final.
- **El calendario es miércoles y domingo, y el miércoles "puede correrse al jueves siguiente en
  caso de feriados"** (texto vigente de la página del juego). Ya vimos en Q1 que en la práctica
  también hay lunes, martes y viernes.

**Borrador:** [`drafts/game_rules_5_de_oro.csv`](../../src/sorteos/uy/reference/game_rules.csv) tiene 29 filas,
cada una con vigencia, resolución y URL.

### Antes de 2012: el decreto de 1989 y un hueco (verificado, UY-007)

El Decreto 635/989 (que la As. 176/2014 cita como marco) está en
[IMPO](https://www.impo.com.uy/bases/decretos/635-1989), consultado el 2026-10-15. **Crea el 5 de
Oro el 28/12/1989 con un rango de 01 a 36**: "consiste en elegir cinco números desde el 01 al 36
inclusive". Fija además el Pozo de Oro en 20% y el de Plata en 3,20% de lo apostado. IMPO lista dos
modificaciones, el Decreto 360/990 y el 155/998, y **ninguna toca el artículo del rango**.

Así que el rango cambió al menos una vez entre 1990 y 2006 (de 01–36 a 01–44), por un instrumento
que no encontramos. Seguramente fue una resolución de la Dirección, porque el decreto le da
facultades para reglamentar el juego.

**Hueco (decisión del owner, 2026-10-15: no bloquea G1):** la resolución del 01–44, y los precios y
porcentajes de 2006 a 2012. Para la v1 alcanza con lo verificado en los datos, porque la historia
publicada empieza en 2006 y en ese período el rango es 01–44 sin excepciones. Si la resolución
aparece, entra en `game_rules` como fuente de una fila que ya existe.

---

## Calendario oficial y `calendar_events`

### `ver_calendario.php` (verificado)

- **Muestra solo el mes en curso.** No acepta parámetros: ni el formulario ni los enlaces piden
  otro mes.
- **Está hecho de imágenes.** Cada día es una imagen con su número (`14.png`) seguida de los logos
  de sus juegos: `logo_tombola_quiniela`, `logo_5deoro`, `logo_quiniela_tombola_5deoro`,
  `logo_loteria_10` y `logo_No_Hay_Sorteos`. Se puede parsear, pero el logo de la Quiniela no
  distingue Vespertina de Nocturna (los sábados lo muestra aunque solo hay Nocturna).
- **Ya refleja los traslados.** El de octubre de 2026 muestra el 5 de Oro el **jueves 15** y no el
  miércoles 14, y marca el lunes 12 como "No hay sorteos".
- **Tiene errores de armado:** el viernes 23 de octubre no aparece en la grilla.

**Consecuencia (UY-043):** sirve como calendario esperado **del mes en curso** para la ingesta
diaria, no para la historia. Hay dos fuentes más del día: el bloque "Sorteos para el día de hoy"
de `ver_resultados` (juegos y horas) y el "Próximo sorteo" del último extracto.

### Suspensiones y traslados (verificado)

`noticias.php` publica las resoluciones de la DNLQ, de ~2013 a hoy, cada una con un resumen
("Trasladar la realización del sorteo del 5 de Oro con Revancha del domingo 19 de julio de 2026
para el lunes 20 de julio de 2026") y su documento (218 PDF, más algunos JPG).

**Borrador:** [`drafts/calendar_events.csv`](../../src/sorteos/uy/reference/calendar_events.csv) tiene 54 eventos, 30
suspensiones y 24 traslados:

- 30 se extrajeron con un parser de los resúmenes.
- 19 se cargaron a mano, por estar redactados de otra forma (OIS escaneados, varias fechas en
  uno).
- 5 vienen del brief (2014–2015) y todavía **no tienen URL**.

**Los 54 coinciden con el manifiesto:** cada suspensión es un día sin esos juegos, y cada traslado
es un juego que falta en la fecha de origen y aparece en la de destino.

Lo que explican:

- **Paros con resolución oficial:**
  - 2017-06-21: paro general de COFE.
  - 2017-07-20: paro general del PIT-CNT.
  - **2019-09-25 y 26:** "paro parcial dispuesto por A.F.A.L." (OIS 2036 y 2037). El 5 de Oro se
    trasladó al 26 y después al 27.
  - 2021-06-17: PIT-CNT y COFE.
  - 2024-04-18 y 2024-08-07.

  Junto con el 2017-08-09 de Q2, ya son al menos siete.
- **2016-12-05:** se suspendió la Nocturna por "inconvenientes técnicos". Es uno de los 17 días
  con solo Vespertina de Q2.
- **2020-08-27 → 2020-08-26:** el 5 de Oro se **adelantó** un día.
- **Fin de 2022:** se suspendieron los sorteos del lunes 26 y el jueves 29 de diciembre, y los
  pozos pasaron al martes 2023-01-03 (Res. 670/2022).
- **2026-01-21:** la Res. 021/2026 confirma lo que había informado el owner en Q1.
- **Semana de Turismo 2020** (OIS 2077) y **2022** (el 5 de Oro del domingo de Pascua pasó al
  martes 19).
- **2020-05-31 → 06-01:** traslado por **duelo nacional** (OIS 2089).

**Límites del borrador:** antes de 2016 la página casi no tiene eventos, así que 2006–2015 sigue
cubierto solo por la regla de "Próximo sorteo" de Q1. El OIS 2038 (27/09/2019) no se leyó: su
fila sale del título. Tampoco se cargaron los cambios de horario (por ejemplo, el de los sábados
del 2022-09-22) ni los traslados de la Lotería.

---

## Q10 — `ver_estadisticas.php` como control cruzado

**Respuesta (verificado): sirve, coincide con nuestros datos, y además encontró un registro mal
fechado en la base del sitio.**

- **Qué es:** un formulario POST que devuelve cuántas veces salió cada número en un rango de fechas
  (`xdia`, `xmes`, `xano` hasta `hdia`, `hmes`, `hano`). Hay uno por juego (`xjue`); el de la
  Quiniela también filtra por posición (1.º a 20.º).
- **No se puede descargar:** la respuesta es solo HTML, sin CSV ni API.
- **Cómo cuenta el 5 de Oro:** solo los 5 números, **sin la bolilla extra**. La "cantidad de
  sorteos consultados" cuenta el 5 de Oro y la Revancha por separado (210 en 2025 = 105 + 105).

**Comparación con el bronce (2 peticiones: 2025 y toda la historia):**

| | Sitio | Bronce | Resultado |
|---|---|---|---|
| 5 de Oro, 2006-01-01 a 2026-09-30 | 10.360 números | 10.360 | **Los 48 conteos iguales** |
| Revancha, mismo rango | 10.365 | 10.360 | 5 de más en el sitio |
| 2025 completo | 525 y 525 | 525 y 525 | Iguales |

**La Revancha de más es un error de fecha en la base del sitio (verificado).** Por bisección de
fechas (13 peticiones) aparece el **2010-10-07**: un jueves sin sorteo según `ver_resultados`. El
extracto PHP de ese día trae el 5 de Oro vacío (`//`, pozos `0,00`) pero una Revancha completa
(06 08 13 40 44, pozo $ 11.495.998,22). Es **la Revancha del 2010-11-07** copiada con el mes
equivocado: mismos números y mismo pozo. Las estadísticas oficiales la cuentan dos veces.

- **Nuestra capa 1 no la ve**, porque `ver_resultados` no lista el 5 de Oro ese día. Está bien que
  no la vea.
- **La plantilla "vacía" puede traer datos a medias.** El clasificador ve el `//` y la marca como
  vacía, aunque tiene una Revancha. Es el único caso conocido.

**Consecuencia (UY-026 / UY-030):** las estadísticas sirven como control agregado del 5 de Oro y de
la Revancha, con una excepción documentada (−1 Revancha el 2010-10-07). La Quiniela por posición
queda para cuando exista su plata.

---

## Q9 — Términos de uso y pie legal

**Se transcribe y se cita. No se saca ninguna conclusión legal.**

- **No encontramos términos de uso, aviso legal ni política de privacidad.** Revisamos los enlaces
  de la página de inicio, `ver_resultados`, el calendario, las estadísticas, las noticias y las
  páginas de los juegos.
- **Pie de página (transcripción del 2026-10-14):** "Ministerio de Economía y Finanzas | Dirección
  Nacional de Loterías y Quinielas Edificio Central: Cerrito 220 Horarios al público: 9:15 a 15:30
  | Central tel.: 2916 0376 Resolución recomendada de monitor: 1360 x 768 o superior | Sitio
  optimizado para Mozilla Firefox".
- **`robots.txt`** (pedido de nuevo el 2026-10-14, `Last-Modified` 2021-06-14): solo tiene grupos
  para `Googlebot`, `Googlebot-Image` y `AdsBot-Google`, todos con `Disallow:` vacío. No hay grupo
  para otros user-agents.
- **No se revisó** el subdominio `www2.loteria.gub.uy` (contactos, sugerencias) ni la sección
  Transparencia.

Si hace falta algo más que esta transcripción, lo decide el owner.

---

## Otros hallazgos de UY-004

- **Mapa completo de los códigos de Lotería (para UY-006).** `ver_resultados_pdf.php` es otra
  versión de la página de resultados. Su `MostrarExtracto()` mapea **75 códigos**, cada uno a un
  extracto PHP por año (`Extracto_Loteria_2026_9.php`, `Extracto_El_Gordo_2025.php`,
  `Extracto_Revancha_2026.php`…). Ahí están los códigos 27–38 que `sources.py` no conoce (Q3).
- **El PDF de prueba de octubre de 2018, en el código del sitio.** `ver_resultados.php` todavía
  tiene la línea comentada `//var filePath = '/extractosweb/20181023v.pdf';`. Es el mismo
  extracto del 23/10/2018 que encontramos dentro de `20181009v.pdf` (Q5).

---

## UY-005 — ¿Se puede llegar al sitio desde AWS?

**Respuesta (verificado el 2026-10-15 a las 00:36 UTC, desde CloudShell en us-east-1, corrido por
el owner): sí, sin proxy.**

**Método.** El script [`drafts/uy005_cloudshell.sh`](drafts/uy005_cloudshell.sh) hace 4
peticiones, a 1 por segundo y con el User-Agent de UY-001, y compara el resultado contra el
bronce local. IP de salida: `44.205.19.58`.

| Petición | Estado | Bytes en AWS | Bytes en local | Tiempo |
|---|---|---|---|---|
| `index.php` | 200 | 23.822 | 23.822 | 0,86 s |
| `ver_resultados` del 2026-09-23 | 200 | 87.841 | 87.421 | 0,76 s |
| Extracto PHP del 5 de Oro del 2026-09-23 | 200 | 11.870 | 11.870 | 0,54 s |
| PDF `20260923o.pdf` | 200 | 352.607 | 352.607 | 0,96 s |

- **No hay CDN ni WAF delante del sitio.** Todas las respuestas traen `Server: nginx`, sin `cf-ray`
  ni otras cabeceras de Cloudflare o de un WAF. No apareció texto de desafío ni de bloqueo.
- **El contenido es el mismo.** El SHA-256 del PDF es idéntico al del bronce (`a1598f7b…`).
  `ver_resultados` trae el `MostrarExtracto('5','23','09','2026')` esperado, y el extracto trae su
  fecha. Los 420 bytes de diferencia en `ver_resultados` son el bloque "Sorteos para el día de
  hoy", que cambia con el día de la petición.
- **No hizo falta probar desde `sa-east-1`.**

**Consecuencias (decisión del owner en UY-003):**

- **Sin proxy.** El extractor de la nube baja el HTML (`ver_resultados` y los extractos PHP) **y el
  PDF del extracto como respaldo**.
- **El PDF de pozos también se baja**, porque es la única fuente del número de sorteo.
- **UY-040 se simplifica:** no hay credenciales de proxy ni costo por petición. Sí se mantienen la
  cortesía (1 req/s) y el guard de `DET_INVALIDAS`.

**Límite.** CloudShell sale por una IP de AWS, como una Lambda, pero no por la misma. La
confirmación definitiva es la primera ejecución real en la Fase 5. Si una Lambda de la VPC del
proyecto sale sin NAT (`enable_internet=false` en prod), además hace falta una ruta de salida, pero
eso es diseño de UY-040 y no un bloqueo del sitio.

---

## Q4 y Q6 — Lotería Uruguaya y Kini

**Contexto.** Los dos juegos están **fuera de la v1** (roadmap: UL1 y UL2). Esta sección deja
documentado lo necesario para sumarlos después, sin implementar nada. Todo sale del bronce y del
manifiesto, más 12 peticiones el 2026-10-15.

### Q4 — Dónde está el extracto de la Lotería (verificado)

`ver_resultados.php` decide la ruta con `MostrarExtracto(código, día, mes, año)`:

- **Sorteos desde el 2018-11-30:** para **cualquier** código de Lotería, el sitio arma el PDF
  `/extractosweb/{aaaammdd}l.pdf` (la `l` es de Lotería, como la `o`, la `v` y la `n` de Q5). El
  código no se usa, así que los 27–38 que `sources.py` no conocía (Q3) ni siquiera tienen otra
  ruta.
- **Sorteos anteriores:** los códigos 1 y 6–26 abren cada uno un extracto PHP distinto
  (`extracto_loteria_2_nvo.php`, `extracto_loteria_fin.php`, `Extracto_Loteria_2014_reyes.php`…).
- **`ver_resultados_pdf.php`** (UY-004) es una versión alternativa de la página de resultados. Su
  mapa llega a 75 códigos, y ofrece también un PHP para cada sorteo posterior a 2018.

**Las plantillas PHP de la Lotería leen el sorteo por la fecha.** Se pidieron, para las fechas de
los códigos 35–38, el PHP que indica el mapa y el del código siguiente, más el PDF `l`:

| Código | Fecha | PHP del mapa | PHP del código siguiente | PDF `l` |
|---|---|---|---|---|
| 35 | 2021-12-30 | 1.º premio 29909 | 29909 | 29909 |
| 36 | 2022-01-21 | 33029 | 33029 | 33029 |
| 37 | 2022-12-30 | 39551 | 39551 | 39551 |
| 38 | 2023-01-20 | 21984 | 21984 | 21984 |

Los dos PHP devuelven los mismos números, que son los del PDF. Solo cambia el título de la página
(por ejemplo, "LOTERÍA ESPECIAL DE AGOSTO 2022" en lugar de "Extracto de LOTERIA URUGUAYA"). **El
corrimiento que parecía haber en el mapa de los códigos 35–38 es cosmético: no cambia los datos.**

**Consecuencia para UL1:** el adaptador de la Lotería pide el PDF `l` desde el 2018-11-30, o un
PHP de Lotería con la fecha (por ejemplo `extracto_loteria_2_nvo.php`, que es el código 1), y no
necesita el mapa de códigos. `game_for_code` solo debería tratar como Lotería todo código que no
sea 2–5 ni 19, en lugar de `unknown_N`. Es un cambio para cuando se implemente UL1, no ahora.

### Q6 — Frecuencia real de la Lotería (verificado)

Hay 436 días con Lotería en `ver_resultados` (contando los códigos 27–38):

| Período | Sorteos por año | Nota |
|---|---|---|
| 2006 (desde el 11/08) | 18 | |
| 2007–2012 | 40 a 43 | Casi semanal |
| 2013 | 14 | Transición |
| 2014–2025 | 11 a 12 | **Mensual** |
| 2026 (hasta el 30/09) | 9 | |

- **Se sortea los viernes:** 416 de 436. Los otros 20 caen de lunes a sábado (observado: en su mayoría
  extraordinarios y traslados).
- **Hay extraordinarios fijos:** el Gordo de fin de año (~30/12) y la Revancha de Reyes (enero),
  que son los códigos 27–38 de Q3. Hubo también ediciones especiales: "200 años" el 2019-07-15 y
  "Especial de Agosto" en 2022 y 2023.
- **Hipótesis:** el paso a mensual coincide con el fin del Kini (2013-12-27), así que quizá hubo
  una reestructuración de los juegos en 2013. No se buscó la resolución.

### Kini (verificado)

- **Juego histórico:** el último sorteo publicado es el **2013-12-27**. El primero en el sitio es
  el 2006-08-15, pero ese es el inicio de la historia del sitio, no del juego: hay noticias del
  Kini en 2005 (informado por el owner).
- **Se sorteaba de lunes a viernes**, unas 245 veces al año: 1.793 sorteos en total.
- **Formato observado:** 5 números distintos entre **01 y 36**, un pozo ("Pozo Kini") y ganadores
  o "Sin Aciertos". Son 1.793 de 1.793 bloques leídos sin error.
- **Los datos ya están en el bronce.** El bloque del Kini viene completo dentro de cada página de
  `ver_resultados`, así que un backfill futuro no necesita ni una petición. El extracto propio es
  el código 2 (`Extracto_QV_QN_K.php`; por el nombre, compartido con la Quiniela, no se pidió).
- **Decisión del owner (2026-10-15):** se queda como **UL2, diferido y solo con backfill**.

**Corrección al roadmap:** el Kini no es "2007–2014" ni "descontinuado en 2014". Lo verificado es
**2006-08-15 a 2013-12-27** en el sitio.
