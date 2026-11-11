# `sql/uy/gold/` — el oro de Uruguay (UY-032, UY-044)

Seis consultas, una por tabla de oro. Cada archivo es **un solo `SELECT`** sobre las tablas de
plata (`silver_draws`, `silver_draw_numbers`, `silver_prizes`, `silver_game_rules`) y nada más:
sin `CREATE TABLE`, sin base ni ubicación. Quien lo corre decide dónde queda el resultado:

- **En local**, `make uy-gold-local` lo corre con DuckDB sobre `data/uy/silver` y escribe
  `data/uy/gold/<tabla>/part-0.parquet` (`scripts/uy_gold_local.py`). No toca AWS.
- **En la nube** (UY-044.3), el constructor lo envuelve en un `CREATE TABLE ... AS` de Athena
  con una ubicación nueva por corrida y después hace el swap.

Cada tabla dice **qué esperaba y qué observó**, y cuántas filas dejó fuera y por qué. El
encabezado de cada archivo lo explica: grano, esperado, observado, exclusiones.

| Archivo | Tabla | Grano | Esperado | Observado |
|---|---|---|---|---|
| `01_gold_digit_frequency.sql` | `gold_digit_frequency` | juego, alcance (total o posición 1–20), lugar del dígito, dígito | cada dígito en 1/10 de los números | su conteo, y el chi-cuadrado del grupo (9 grados de libertad) |
| `02_gold_quiniela_repeats.sql` | `gold_quiniela_repeats` | juego, alcance (total o año) | 17,41 % de los sorteos repite un número | la tasa, con su puntaje z |
| `03_gold_tombola_replacements.sql` | `gold_tombola_replacements` | juego, alcance (total o año) | 1,79 reemplazos por sorteo | la media, la misma cuenta hecha desde la Quiniela y el puntaje z |
| `04_gold_5_de_oro_frequency.sql` | `gold_5_de_oro_frequency` | rango de números (01–44, 01–48), tipo de bolilla, número | cada número igual de seguido | su conteo, y el chi-cuadrado ajustado por sorteo sin reposición |
| `05_gold_pool_dynamics.sql` | `gold_pool_dynamics` | sorteo, premio (oro, plata, revancha) | el pozo sube si nadie ganó y baja si alguien ganó | qué hizo el pozo siguiente, y si coincide |
| `06_gold_punctuality.sql` | `gold_punctuality` | juego, alcance (total o año) | la Vespertina arranca a las 15:00 y la Nocturna a las 21:00 | cuántos sorteos arrancan a esa hora, y cuánto duran |

## Cómo leer los resultados

- **Un rechazo no es un bolillero cargado.** `gold_digit_frequency` hace 126 pruebas y
  `gold_5_de_oro_frequency` 6. Al 5 %, unas seis de las 126 rechazan por azar aunque todo sea
  uniforme. Lo que se mira es cuántas rechazan, no cuál.
- **Los valores críticos** del chi-cuadrado (5 % y 1 %) están escritos en el SQL para los
  grados de libertad que hacen falta (9, 43 y 47). Un test los recalcula con `scipy`. No hay
  valor p: sale de una función que Athena no tiene (owner, 2026-11-11, 2a).
- **`gold_pool_dynamics` es una hipótesis, no una regla del juego.** La tabla dice en qué
  proporción de los sorteos se cumple para cada pozo; que no se cumpla es un hallazgo sobre
  cómo se arma ese pozo, no un error de datos.
- **Los montos son pesos nominales** (D6). Nada aquí ajusta por inflación.
- **Las exclusiones** siguen el catálogo de `dq_flags` (D22) y se cuentan en la tabla
  (`draws_excluded`, `excluded_reason`).

## Un SQL, dos motores

El SQL está escrito para Athena (motor 3, Trino) y DuckDB lo corre tal cual. Para que los dos
den lo mismo, las consultas evitan lo que cada uno lee distinto (probado el 2026-11-11 sobre la
plata real; `tests/unit/sorteos/test_uy_gold_sql.py` lo vigila):

| No usar | Por qué | En su lugar |
|---|---|---|
| `day_of_week`, `date_add('day', n, d)`, `approx_percentile` | DuckDB no las tiene con esa forma | — (ninguna consulta las necesita hoy) |
| `sequence(1, n)` / `range` / `generate_series` | cada motor tiene la suya | una lista `VALUES` |
| `a / b` entre enteros | Athena da un entero, DuckDB un número con decimales | `CAST(a AS double) / b` |
| un literal como `16.919` sin tipo | DuckDB lo lee como `decimal`, Athena como `double` | `CAST(... AS double)` |
| `year(fecha)` sin tipo | Athena da `bigint` | `CAST(year(fecha) AS integer)` |
| un alias usado en el mismo `SELECT` | DuckDB lo acepta, Athena no | un CTE más |
| la columna de partición `year` | DuckDB la infiere `bigint` | `scripts/uy_gold_local.py` la declara `INTEGER` |

Funcionan igual en los dos: `CROSS JOIN UNNEST`, `contains(array, x)`, `count_if`,
`agg(...) FILTER (WHERE ...)`, las funciones de ventana, `date_diff('minute', a, b)`, `hour`,
`minute`, `lpad`, `stddev_samp`, `VALUES ... AS t (col, ...)`.

Las seis consultas se corrieron también en Athena (`lottery-uy-wg`) contra la plata de
`uy/silver/` y cada fila se comparó con la de DuckDB: iguales (el resultado está en el PR de
UY-044.2). UY-044.3 repite esa comparación sobre las tablas publicadas.
