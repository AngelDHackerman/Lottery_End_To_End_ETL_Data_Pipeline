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
| **Q3** | Fecha más antigua por juego | **Respondida** (verificado: 2006-08-11 en `ver_resultados` y en los extractos PHP; PDF desde el 2018-11-30) | UY-002 + UY-003 |
| Q4 | Rutas de Lotería y Kini | Respondida en el Tracker, falta la sección | UY-006 |
| **Q5** | PDF frente a HTML | **Respondida** (verificado: el PDF es una impresión del HTML y coincide en el 100% de los campos) | UY-003 |
| Q6 | Frecuencia de la Lotería | Pendiente | UY-006 |
| **Q7** | Encoding | **Respondida** (verificado: UTF-8 en el HTML; el texto de los PDF sale con tildes correctas) | UY-002 + UY-003 |
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

- **El Kini no aparece después de 2013-12-27** (verificado en `ver_resultados`). Si dejó de
  sortearse o cambió de nombre se ve en UY-006.
- **Códigos de Lotería que `sources.py` no conoce (verificado):** 15 páginas, del 2018-12-29 al
  2023-01-20, traen códigos `MostrarExtracto` del **27 al 38**. `game_for_code` solo reconoce como
  Lotería el 1 y del 6 al 26, así que quedan como `unknown_27` … `unknown_38`. Caen siempre a fin de
  diciembre o entre el 15 y el 24 de enero. Hipótesis: sorteos extraordinarios de Lotería (fin de
  año y Reyes), con un código nuevo cada año. Se resuelve con las rutas de Lotería en UY-006 (Q4).

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
