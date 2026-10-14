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
| **Q2** | Fecha sin sorteo y Quiniela en fin de semana | **Respondida** (verificado; los 4 `error` de 2019 son un paro) | UY-002 |
| Q3 | Fecha más antigua por juego | **Respondida para `ver_resultados`** (verificado, 2006-08-11); falta `extractosweb` | UY-002 + UY-003 |
| Q4 | Rutas de Lotería y Kini | Respondida en el Tracker, falta la sección | UY-006 |
| Q5 | PDF frente a HTML | Parcial (PDF desde 2018-11-30, ver C9); falta la comparación | UY-003 |
| Q6 | Frecuencia de la Lotería | Pendiente | UY-006 |
| Q7 | Encoding | **Respondida para el HTML** (verificado, UTF-8); falta el texto de los PDF | UY-002 + UY-003 |
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
| **2019-09-25** | | **Paro de AFAL, el gremio de la DNLQ** (informado por el owner y confirmado en [prensa](https://focusgn.com/latinoamerica/loterias-uruguayas-apuestas)): rechazo a eliminar a los "niños cantores" de las extracciones. Ese 5 de Oro se sorteó el **martes 2019-10-01**. Coincide con los 4 días `error` (25, 26, 27 y 30 de septiembre), en los que tampoco hubo Quiniela. Detalle en [Q2](#los-4-días-error-de-septiembre-de-2019-paro-verificado). |
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
  (2006-08-01 a 2006-08-10, ver [Q3](#q3--fecha-más-antigua-de-cada-juego-parte-ver_resultados))
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
figura del "niño cantor" en las extracciones (informado por el owner). Lo confirma una nota de
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

**Propuesta (se decide en UY-010 / UY-011):** el clasificador queda estricto. Los 4 días se pasan a
`no_draw` con una corrección manual en el manifiesto, que cita una fila de `calendar_events`
(causa `paro`, con la URL de la nota). Un `error` nuevo sigue pidiendo revisión humana.

**Pendiente:** las 4 páginas no quedaron en bronce, porque bronce solo guarda sorteos. Para tener una
como fixture hay que volver a pedirla (1 petición).

---

## Q3 — Fecha más antigua de cada juego (parte `ver_resultados`)

**Respuesta (verificado):** la historia empieza el **2006-08-11**, no el 07/01/2007 que daba el brief
(ver C8 en el roadmap). Del 2006-08-01 al 2006-08-10 la página sale vacía.

| Juego | Primer día | Último día en el backfill | Páginas |
|---|---|---|---|
| Lotería | 2006-08-11 | 2026-09-18 | 421 |
| Quiniela Nocturna | 2006-08-11 | 2026-10-03 | 5.935 |
| Kini | 2006-08-15 | **2013-12-27** | 1.793 |
| Quiniela Vespertina | 2006-08-16 | 2026-10-02 | 4.943 |
| 5 de Oro | 2006-08-16 | 2026-09-30 | 2.072 |

- **El Kini no aparece después de 2013-12-27** (verificado en `ver_resultados`). Si dejó de
  sortearse o cambió de nombre se ve en UY-006.
- **Códigos de Lotería que `sources.py` no conoce (verificado):** 15 páginas, del 2018-12-29 al
  2023-01-20, traen códigos `MostrarExtracto` del **27 al 38**. `game_for_code` solo reconoce como
  Lotería el 1 y del 6 al 26, así que quedan como `unknown_27` … `unknown_38`. Caen siempre a fin de
  diciembre o entre el 15 y el 24 de enero. Hipótesis: sorteos extraordinarios de Lotería (fin de
  año y Reyes), con un código nuevo cada año. Se resuelve con las rutas de Lotería en UY-006 (Q4).
- La parte de `extractosweb` (desde qué fecha responde cada extracto) va en UY-003.

---

## Q7 — Encoding (parte HTML)

**Respuesta (verificado): todo es UTF-8 y no hay que adivinar nada.**

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

La parte de los PDF (el encoding del texto extraído) va en UY-003.
