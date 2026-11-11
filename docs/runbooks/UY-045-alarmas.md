# UY-045 — las alarmas de Uruguay

Qué significa cada correo, qué mirar primero y cómo se apaga. Todas publican en el tópico
`loteria-alerts-prod`, el mismo de Santa Lucía.

| Alarma | Suena cuando | La ejecución |
|---|---|---|
| `lottery-uy-pipeline-prod-failed` (UY-043.3) | una ejecución falló o se pasó de la hora | `FAILED` / `TIMED_OUT` |
| `lottery-uy-open-draw-gaps-prod` | hay un hueco `open` en `draw_gaps` | `SUCCEEDED` |
| `lottery-uy-silver-quarantine-prod` | la plata tiene filas en cuarentena | `SUCCEEDED` |
| `lottery-uy-fetch-errors-prod` (el canario) | la corrida dejó claves en `error` | `SUCCEEDED` |
| `lottery-uy-pipeline-prod-no-success-2d` | ninguna ejecución exitosa en 2 días | no hubo, o todas fallaron |

Las tres del medio son **de estado**: mandan un correo cuando la cuenta deja de ser 0 y quedan en
`ALARM` hasta que una noche publique 0. Vuelven a `OK` unas dos horas después de esa noche
limpia. No mandan correo al recuperarse.

## De dónde salen los números

Cada noche real, las Lambdas escriben una línea en su grupo de logs con el formato Embedded
Metric Format, y CloudWatch la convierte en métricas del namespace `Loteria/UY` (dimensión
`Environment=prod`):

| Métrica | Quién | Qué cuenta |
|---|---|---|
| `FetchRequests` | fetch | peticiones al sitio en la corrida |
| `FetchErrors` | fetch | claves que quedaron en `error` |
| `OpenDrawGaps` | silver | filas de `draw_gaps` con `status = 'open'` |
| `SilverQuarantineRows` | silver | filas en `quarantine` |

Un dry run no publica nada. Una noche que no corre tampoco, y por eso esas tres alarmas tratan
la falta de dato como "todo bien": la noche que no corrió es asunto del dead-man.

```bash
# Lo que se publicó en los últimos tres días.
for m in FetchRequests FetchErrors OpenDrawGaps SilverQuarantineRows; do
  aws cloudwatch get-metric-statistics --namespace Loteria/UY --metric-name $m \
    --dimensions Name=Environment,Value=prod --statistics Maximum --period 3600 \
    --start-time "$(date -u -d '3 days ago' +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" \
    --query 'sort_by(Datapoints,&Timestamp)[].[Timestamp,Maximum]' --output text | sed "s/^/$m /"
done

# El estado de las cinco.
aws cloudwatch describe-alarms --alarm-name-prefix lottery-uy- \
  --query 'MetricAlarms[].[AlarmName,StateValue,StateUpdatedTimestamp]' --output table
```

## `open-draw-gaps`: falta un sorteo

Un sorteo que debía salir no salió en su ventana (la fecha esperada más 3 días) y ninguna fila
de `calendar_events` lo explica. La alarma llega unos 4 días después de la fecha esperada.

```sql
-- workgroup lottery-uy-wg
SELECT game, previous_draw_date, expected_date, expected_from, window_end, next_draw_date
FROM lottery_uy_db.silver_draw_gaps
WHERE status = 'open';
```

- **El sorteo se suspendió o se movió** (feriado, paro, duelo): buscar la resolución en
  `noticias.php` del sitio, agregar la fila a `src/sorteos/uy/reference/calendar_events.csv`
  con su fuente (el archivo es CRLF) y desplegar. La corrida siguiente pasa el hueco a
  `explained` y la alarma vuelve a `OK`.
- **El sitio lo publicó tarde**: no hay nada que hacer. La corrida que lo baje cierra el hueco.
- **El sitio no responde**: habrá sonado también el canario. Ver abajo.

## `silver-quarantine`: una página no se pudo leer

El parser apartó filas de una página que el manifiesto tiene como sorteo. Casi seguro el sitio
cambió su HTML. **Mientras haya cuarentena, `draw_gaps` no se reescribe** (un detector sobre una
plata incompleta inventaría huecos), así que la alarma de huecos queda ciega.

```sql
SELECT * FROM lottery_uy_db.silver_quarantine;
```

`$.silver.report` de la ejecución trae la cuenta por año y `ok: false`. El arreglo es del parser
(una época nueva, D5), con la página como fixture.

## `fetch-errors`: el canario

`$.fetch.report.by_state` de la última ejecución dice cuántas claves quedaron en `error`.

- **Una o dos**: lo normal es un PDF que el sitio niega (pasó con 34 PDF de pozos en el
  backfill). Se vuelve a pedir cada noche y, a la tercera falla igual, pasa a `missing` (D11) y
  la alarma se apaga sola.
- **Muchas, o `resultados` entre ellas**: el sitio bloquea o cambió. `make uy-fetch-probe` pide
  la última página de cada fuente (8 peticiones) y dice cuáles responden.

Nada se pierde: toda clave en `error` se vuelve a pedir la noche siguiente.

## `no-success-2d`: el pipeline no corre

Ninguna ejecución terminó bien en dos días.

```bash
aws scheduler get-schedule --name lottery-uy-nightly-prod --query '[State,ScheduleExpression]'
aws stepfunctions list-executions --max-results 5 --query 'executions[].[name,status,startDate]' \
  --state-machine-arn arn:aws:states:us-east-1:913524903233:stateMachine:lottery-uy-pipeline-prod
```

Si el schedule está `ENABLED` y no hay ejecuciones, mirar el rol `lottery-uy-scheduler-prod`. Si
hay ejecuciones y todas fallan, la causa está en la primera. `make uy-sfn-run` lanza una a mano;
la ventana de fetch arranca después del último día que tiene el manifiesto, así que una sola
corrida se pone al día. Un dry run que termina bien también cuenta como éxito para esta alarma.

## Probar que el correo llega

Sin tocar métricas (vuelve sola a su estado en la evaluación siguiente):

```bash
aws cloudwatch set-alarm-state --alarm-name lottery-uy-fetch-errors-prod \
  --state-value ALARM --state-reason "prueba del camino de notificación (UY-045)"
```
