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
nuevas**. Los cupones se citan solo por su formato (`#########-#`), nunca por su valor (decisión C7
pendiente).

---

## Resumen por pregunta

| Pregunta | Tema | Estado | PR |
|---|---|---|---|
| **Q1** | El 5 de Oro en `ver_resultados` y sus campos | **Respondida** (verificado, campos y valores) | UY-002 |
| Q2 | Fecha sin sorteo y Quiniela en fin de semana | Respondida en el Tracker, falta la sección | UY-002 |
| Q3 | Fecha más antigua por juego | Respondida (2006-08-11, ver C8), falta la sección | UY-002 + UY-003 |
| Q4 | Rutas de Lotería y Kini | Respondida en el Tracker, falta la sección | UY-006 |
| Q5 | PDF frente a HTML | Parcial (PDF desde 2018-11-30, ver C9); falta la comparación | UY-003 |
| Q6 | Frecuencia de la Lotería | Pendiente | UY-006 |
| Q7 | Encoding | Respondida (UTF-8 en todas las páginas), falta la sección | UY-002 + UY-003 |
| Q8 | Rango y reglas del 5 de Oro | Pendiente | UY-004 |
| Q9 | Términos de uso | Pendiente | UY-004 |
| Q10 | `ver_estadisticas` como control cruzado | Pendiente | UY-004 |
| — | Acceso desde AWS | Pendiente | UY-005 |

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
| **2019-09-25** | | **Huelga del gremio de la DNLQ** (informado por el owner): rechazo a eliminar a los "niños cantores" de las extracciones. Ese 5 de Oro se sorteó el **martes 2019-10-01**. Coincide con los 4 días `error` (25, 26, 27 y 30 de septiembre), en los que tampoco hubo Quiniela. |
| **2026-01-21** | | **Cambio de calendario de la DNLQ** (informado por el owner): para no superponerse con el sorteo extraordinario "La Revancha de Reyes" del viernes 2026-01-23, las apuestas pasaron al domingo 2026-01-25. El manifiesto lo confirma: el 23 trae un bloque `loteria` y el 25 trae el 5 de Oro. |
| **2016-04-17** | | **Duelo Oficial nacional** (informado por el owner) decretado por el Poder Ejecutivo tras el tornado F3 de Dolores (Soriano) del 2016-04-15. Durante un duelo oficial, la DNLQ suspende la comercialización y los sorteos públicos. El sorteo anterior lo había anunciado y el siguiente fue el 2016-04-20. |
| **Sin explicar (2)** | 2006-08-27, 2006-08-30 | Caen en las dos primeras semanas de la historia publicada. Hipótesis: carga incompleta al arrancar el sitio. Esos mismos sorteos tampoco anuncian el próximo, así que no hay forma de confirmarlo con los datos. |

**Pendiente:** las páginas `error` de septiembre de 2019 no quedaron en bronce, porque bronce solo
guarda sorteos. Para documentar qué muestran hay que volver a pedir esas 4 URLs (4 peticiones).

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
- **Rango observado de 01 a 48** en las dos épocas (2006–2016 y 2016–2026), tanto en el 5 de Oro
  como en la Revancha y la extra. Es **observado** y no una regla: el rango oficial y sus
  versiones se confirman con las resoluciones en Q8 (UY-004). El brief había visto como máximo
  46.

**Ganadores: "Vacío" es distinto de "Sin Aciertos" (verificado).** En `ver_resultados` hay:

| Premio | Cupones | Sin Aciertos | Vacío |
|---|---|---|---|
| Oro | 543 | 1.518 | 11 |
| Plata | 1.445 | 621 | 6 |
| Revancha | 509 | 1.555 | 8 |

Las 25 celdas vacías (6 en los dos primeros sorteos de 2006 y el resto repartido entre 2006 y 2026)
están vacías también en el extracto. Hipótesis: el dato no se cargó. En plata deben quedar como
"desconocido", no como "Sin Aciertos" ni como "con ganadores".

## Pendiente de Q1

- Sumar los traslados de fecha a `calendar_events` con su resolución (UY-004).
