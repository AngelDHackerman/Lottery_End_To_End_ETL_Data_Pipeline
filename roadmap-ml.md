# Roadmap — Fase de ML: ¿son aleatorias las loterías? (Uruguay primero, después Guatemala)
**Owner:** Angel Hernandez
**Rama base:** `master` (cada PR sale de `master` y vuelve a `master`)
**Empieza:** después de que #175 (Uruguay → `master`) y PR-036 (README) estén mergeados. Antes de eso, este archivo es solo el plan
**Última actualización:** 2026-11-18 (plan inicial; decisiones del owner del 2026-11-18 anotadas abajo)

> Esta es la última fase del proyecto. El roadmap principal ([`roadmap.md`](./roadmap.md)) y el de
> Uruguay (`roadmap-uruguay.md`, que llega con #175) siguen vigentes, y este archivo **no** los
> edita (ver regla 6).
>
> **Objetivo:** usar estadística y ML para responder dos preguntas con rigor:
> 1. ¿Los sorteos se distinguen del azar? Y si no, ¿cuál es el sesgo más chico que habríamos
>    podido detectar?
> 2. ¿Hay anomalías, en los sorteos o alrededor de ellos (pozos, vendedores, premios vendidos), que
>    merezcan una explicación?
>
> **No es predecir el próximo número.** En una lotería justa ningún modelo le gana al azar. El ML
> aparece aquí como **detector**: si un modelo predice o distingue mejor que el azar, de forma
> significativa y fuera de muestra, hay dependencia o sesgo. Si no lo hace, el resultado honesto
> es "no se distingue del azar, con esta potencia".
>
> **Para qué sirve, además del resultado:**
> 1. **Una charla en el AWS Community Group.** Explica cómo se pone a prueba la aleatoriedad, el
>    control negativo, el pipeline en SageMaker y los errores que encontramos.
> 2. **La certificación AWS Certified Machine Learning Engineer – Associate (MLA-C01).** Cada
>    fase de SageMaker está mapeada a un dominio del examen (ver la tabla «Mapa a la certificación»).

---

## Decisiones del owner (2026-11-18)

| # | Decisión | Elegida | Por qué |
|---|---|---|---|
| D-ML1 | Plataforma | **SageMaker AI** (no Databricks) | Para aprender y por la certificación MLA-C01. Además encaja con el stack (S3, Glue Catalog, Athena, Step Functions, IAM, Lake Formation). Databricks queda como demo opcional (ML-L3) |
| D-ML2 | Orden | **a) primero estadística local**, sin infraestructura nueva | Valida las ideas sin gastar ni abrir permisos. La nube solo recibe lo que ya demostró valer |
| D-ML3 | Alcance | **a) Uruguay primero** | Unos 13.000 sorteos contra unos 120 de Santa Lucía: mucha más potencia estadística. Guatemala entra en la Fase 4 |
| D-ML4 | Planificación | **a) este archivo**, con IDs `ML-NNN` | El mismo método que con Uruguay |

---

## Reglas de trabajo

1. **Un PR por cambio lógico.** Ramas `feat/ML-NNN-slug` (o `docs/`, `fix/`) desde `master`, PR hacia
   `master`. **Nunca apilar PRs** (la lección de #37→#40).
2. **Cada PR actualiza el Tracker** al final de este archivo.
3. **El trabajo de rama va en un `git worktree`.** El árbol principal se queda en `master` porque el
   owner despliega desde ahí.
4. **Exploratorio frente a confirmatorio.** Todo resultado lleva una de las dos etiquetas. Es
   **confirmatorio** solo si la hipótesis, la prueba, el umbral y la corrección estaban escritos en
   el plan de análisis (ML-001) **antes** de mirar los datos que la confirman. Los hallazgos de
   UY-032 son exploratorios por definición: se encontraron mirando.
5. **Siempre corregir por pruebas múltiples.** Se usa Benjamini-Hochberg (FDR) en las familias de
   pruebas, y Bonferroni cuando la familia es chica y se quiere una afirmación fuerte. Un valor p
   suelto, sin decir cuántas pruebas se corrieron, no se publica.
6. **No se editan `roadmap.md` ni `roadmap-uruguay.md`.** Cuando una fase cierre, el roadmap
   principal recibe a lo sumo una fila en su tracker que apunte aquí.
7. **Las reglas de juego no se inventan.** Rangos, cantidad de bolillas y reglas de reemplazo y de
   pozo salen de `game_rules` (con su vigencia) o de una resolución citada. Si una prueba necesita
   una regla que no está, la prueba espera.
8. **Cada métrica dice qué esperaba y qué observó**, igual que el oro de UY-032.
9. **Privacidad:** `DET_INVALIDAS` sigue sin tocarse. En Guatemala, los nombres de vendedores son
   datos públicos del sitio, pero la charla y el reporte los agregan (departamento o ciudad) y no
   señalan a personas: una anomalía estadística no es una acusación.
10. **No hay contacto proactivo con las fuentes.** Si aparece algo raro se documenta, no se reporta
    al operador (decisión del owner del 2026-10-24).
11. **Seguridad en AWS** (lo que dejó PR-052): nada de `AmazonSageMakerFullAccess`, nada de dominios
    de Studio permanentes y nada de endpoints en tiempo real encendidos. **Otro proyecto (cripto)
    comparte la cuenta**, así que su rol de SageMaker nunca se toca.

---

## Lo que ya existe y de dónde se parte

**Verificado** (UY-032, dentro de UY-044.2, #166, sobre 13.016 sorteos):

| Métrica | Observado | Lectura |
|---|---|---|
| Dígitos de la Quiniela (126 chi-cuadrado) | 4 rechazan al 5 % y 1 al 1 % | Por azar se esperan ~6 al 5 %: **compatible con el azar** |
| Repetidos de la Quiniela | Nocturna 18,12 % · Vespertina 16,95 % contra 17,41 % esperado (z 1,46 / −0,85) | Compatible |
| Reemplazos de la Tómbola | 1,802 / 1,769 contra 1,791 | Compatible |
| 5 de Oro, 6 pruebas por versión de reglas | 5 no rechazan; **la bolilla extra de la época 01–44 (779 sorteos) rechaza al 1 %** (77,8 contra un crítico de 67,5) | **La única anomalía abierta**, y es exploratoria. Con 6 pruebas al 1 %, la probabilidad de al menos un rechazo por azar es ≈ 6 % |
| Pozos | Oro y Revancha se comportan como se espera en el 97,3 % de los sorteos. Pozo de Plata, solo en el 54,1 % | Probablemente una regla distinta, no una anomalía. Hay que leer la regla (ML-024) |
| Puntualidad | Duraciones máximas de 610 y 381 min | Horas mal tipeadas en el origen (calidad de datos) |

**Los datos** (la plata de Uruguay, `lottery_uy_db`): `draws` (fecha, horas, número de sorteo,
`dq_flags`), `draw_numbers` (largo: `ball_type`, `position`, `is_draw_order`, `number` con sus
ceros, `is_replacement`), `prizes` (`pool_amount`, `winners_status`, `winning_coupons`), `game_rules`
con vigencia, `calendar_events`, `draw_gaps` y la cuarentena. Todo tiene linaje
(`run_id`, `source_key`, `parser_version`).

**Santa Lucía** (`lottery_santalucia_db`): `silver_sorteos_sorteos` y `silver_premios_premios`
(`numero_premiado`, `letras`, `monto`, `vendedor`, `ciudad`, `departamento`), unos 120 sorteos y
unos 128.000 premios. Para la Fase 4 importan dos cosas:
- **La tabla mezcla números sorteados con premios derivados.** DT, TT, centenas y reintegros salen
  de forma determinista de los números sorteados. Las pruebas de aleatoriedad tienen que usar
  **solo los números sorteados**. Si no, encuentran patrones falsos.
- **Solo algunos premios traen la línea `VENDIDO POR` / `NO VENDIDO`** (11.768 líneas de 145.680 en
  el corpus del 2026-09-27). Hay que confirmar a qué premios se aplica antes de diseñar ML-041.

---

## Potencia estadística: qué se puede detectar con estos datos

Es una aproximación a 3σ que ML-013 tiene que reemplazar con una simulación:

| Juego | Observaciones | Sesgo detectable aprox. |
|---|---|---|
| Quiniela, dígitos agregados | ~10.900 sorteos × 20 números | **~2 %** relativo por dígito |
| Quiniela, por posición | ~10.900 por celda | ~9 % |
| 5 de Oro, época 01–48 | ~1.300 sorteos | **~25 %** por bolilla: solo sesgos grandes |
| Santa Lucía | ~120 sorteos | Poca potencia por sorteo. Su fuerza está en vendido/no vendido y en la geografía |

---

# Fase 0 — Preparación (después de #175 y PR-036)

## ML-000 — Este roadmap
Este archivo, sin código. **Aceptación:** el owner lo aprueba y queda mergeado en `master`.

## ML-001 — Plan de análisis pre-registrado
**Objetivo:** escribir **antes de correr nada nuevo** qué hipótesis se ponen a prueba, con qué
prueba, con qué α, con qué corrección y con qué datos.
- Lista cerrada de hipótesis H1..Hn por juego, cada una con su prueba y su familia de corrección.
- **Corte de confirmación:** los sorteos posteriores a la fecha de merge de ML-001 forman el
  conjunto confirmatorio (crece cada noche y nadie lo mira hasta ML-016). Las fechas anteriores son
  exploratorias.
- Qué cuenta como "anomalía" para el detector (ML-023) y qué se hace con ella: se cruza con
  `dq_flags` y, si no tiene explicación, se anota.
- **Aceptación:** `docs/ml/ANALYSIS_PLAN.md` mergeado. Cambiarlo después de ver datos exige un PR
  que diga qué cambió y por qué.

## ML-002 — Entorno local y paquete
- El código vive en `src/sorteos/ml/`, como paquete testeado y agnóstico del país (encima de
  `sorteos.core`). Los notebooks de `notebooks/ml/` solo llaman al paquete: nada de lógica en celdas.
- Un extra `ml` en `pyproject.toml` (`scipy`, `statsmodels`, `scikit-learn`, `lightgbm`, `ruptures`,
  `duckdb`, `matplotlib`). Es un archivo compartido con #175, **así que va después del merge**.
- Semillas fijas y versiones bloqueadas: cada número de la charla tiene que poder reproducirse.
- **Aceptación:** `make ml-test` en verde y CI corriendo los tests del paquete.

---

# Fase 1 — Estadística local (Uruguay)

| ID | Qué | Notas y aceptación |
|---|---|---|
| ML-010 | **Snapshot de datos** | La plata de `uy/silver/` se baja (solo lectura) a `data/ml/` con un manifiesto de hashes y la `run_id` de origen. Todo análisis cita su snapshot. No se commitea (va en `.gitignore`, como `data/uy`) |
| ML-011 | **Simulador del modelo nulo** | Genera sorteos perfectamente aleatorios con las reglas de cada época, desde `game_rules`: rango del 5 de Oro, Quiniela con repetidos, Tómbola con reemplazos. **Aceptación:** sobre 1.000 historias simuladas, cada prueba de ML-012 rechaza a su α nominal (calibración del falso positivo) y el simulador reproduce el 17,41 % de repetidos y el 1,791 de reemplazos |
| ML-012 | **Batería clásica** | Chi-cuadrado (número, dígito, posición) · runs test · autocorrelación con rezagos 1..k · prueba de huecos (tiempo entre apariciones contra la geométrica) · pares del 5 de Oro contra la hipergeométrica · las pruebas aplicables de NIST SP 800-22 sobre los dígitos de la Quiniela (~650.000). BH por familia |
| ML-013 | **Análisis de potencia por simulación** | Inyecta sesgos conocidos en el simulador (una bolilla un x % más probable, una dependencia entre sorteos) y mide con qué probabilidad los detecta cada prueba. **Entrega la tabla de sesgo mínimo detectable que reemplaza a la de arriba** |
| ML-014 | **Detección de cambios en el tiempo** | CUSUM y change-point (`ruptures`) sobre el chi-cuadrado en ventana móvil. Los cambios esperados (el rango 44→48 del 2014-03-19) tienen que aparecer: son el control positivo. Un cambio sin evento en `calendar_events` se anota |
| ML-015 | **La bolilla extra del 5 de Oro (01–44)** | Exploratorio: ¿se saca del mismo bolillero, después de las 5? ¿Su distribución condicional es la que se supone? ¿Se concentra en algún subperíodo? Esa época terminó, así que **no puede confirmarse con datos nuevos**: se documenta como abierta o explicada, sin forzar |
| ML-016 | **Corrida confirmatoria** | Corre H1..Hn de ML-001 sobre el conjunto confirmatorio. Se hace una sola vez, al cierre de la fase |

**G1 — puerta de la Fase 1:** el owner revisa los resultados de ML-012 a ML-016. Pasan a la Fase 2
solo las pruebas que estén calibradas en ML-011.

---

# Fase 2 — ML local (Uruguay)

| ID | Qué | Notas y aceptación |
|---|---|---|
| ML-020 | **Variables por sorteo** | Suma, pares/impares, dispersión, repetidos, entropía de dígitos, reemplazos, duración, hora de inicio, día de la semana. Se calculan igual para sorteos reales y simulados |
| ML-021 | **Classifier Two-Sample Test (C2ST)** — la pieza central | LightGBM distingue sorteos reales de sorteos simulados (ML-011). Validación cruzada temporal y nulo por permutación de etiquetas. **Resultado esperado: precisión ≈ 50 %.** Si sale más, la importancia de variables dice en qué se distinguen. Antes de afirmar nada, se busca un error del simulador o de los datos |
| ML-022 | **Prueba de predictibilidad** | Predecir "sale el número k" o "dígito de la posición p" a partir de los sorteos anteriores. Modelos: regresión logística, LightGBM y un LSTM solo para comparar. Nulo: el mismo modelo con el orden de los sorteos barajado. Se espera un AUC ≈ 0,5 con su intervalo |
| ML-023 | **Detector de anomalías por sorteo** | Isolation Forest sobre ML-020. Cada sorteo marcado se cruza con `dq_flags`. La mayoría van a ser errores de la fuente (las duraciones de 610 min), y eso también es un resultado: el ML le devuelve trabajo al DQ |
| ML-024 | **Pozos y ganadores** | Primero se lee la regla del pozo (qué porcentaje de la venta va a cada pozo; regla 7). Con eso se estiman las ventas desde el crecimiento del pozo y se comparan los ganadores esperados (binomial) contra `winning_coupons`. El Pozo de Plata (54,1 %) se explica por su regla o queda abierto |

**G2 — puerta de la Fase 2:** se decide qué pasa a la nube. Lo esperado: la batería (ML-012), el
C2ST (ML-021) y el detector (ML-023).

---

# Fase 3 — SageMaker AI (Uruguay en la nube)

> Todo en **batch**, sin endpoints. Los datos son chicos (cabe en pandas), así que el costo de
> cómputo es marginal. Lo que se aprende aquí es MLOps, que es lo que pide el examen.

| ID | Qué | Trampas conocidas y aceptación |
|---|---|---|
| ML-030 | **Diseño, seguridad y costos** | ¿Un stack aparte `terraform/ml/` con su propio estado (el patrón de `terraform/uy/`), o va dentro de `terraform/uy/`? (D-ML5). Un rol de ejecución mínimo: lectura de `uy/silver/` y escritura en `uy/ml/`, sin `FullAccess`. **Lake Formation:** grants por tabla más `lakeformation:GetDataAccess` (las dos cosas, nunca `ALL`). Un AWS Budget con alarma. El precio real de cada pieza (Processing, MLflow, Model Monitor) se mide en la calculadora antes de aplicar |
| ML-031 | **El paquete en un contenedor** | Imagen en ECR, con tags inmutables y escaneo (el patrón de `lottery-uy-silver-prod`). El mismo `src/sorteos/ml/` que corre en local. **Aceptación:** la misma entrada da la misma salida en local y en SageMaker, byte a byte |
| ML-032 | **SageMaker Processing job** | Corre la batería, el C2ST y el detector sobre la plata y escribe Parquet en `uy/ml/<tabla>/run=<generación>/`. Las tablas del catálogo se declaran en Terraform y se publican con el swap atómico de UY-044 |
| ML-033 | **Orquestación** | Opción a: un paso más en `lottery-uy-pipeline-prod` (Step Functions, `.sync`). Opción b: **SageMaker Pipelines** disparado por EventBridge cuando la máquina de UY termina bien. La b vale más para el examen (D-ML6). **No** corre en un dry run. Una falla es la falla de la ejecución, con alarma |
| ML-034 | **Experimentos y registro** | MLflow gestionado en SageMaker para runs, métricas y artefactos; Model Registry para el detector, con aprobación manual. **Ojo con el costo:** el tracking server cobra por hora encendido (confirmar si hoy hay opción serverless). Encenderlo solo para entrenar, o usar un modo sin servidor |
| ML-035 | **Random Cut Forest frente a Isolation Forest** | RCF es el algoritmo de anomalías que trae SageMaker: Training job + Batch Transform. Se comparan los dos detectores sobre los mismos sorteos (¿coinciden en los marcados?). Es material directo del examen y de la charla |
| ML-036 | **Monitoreo** | Alarma si una prueba rechaza después de la corrección o si el detector marca un sorteo sin `dq_flags`. Deriva de las variables con Model Monitor sobre Batch Transform, o un Processing propio si sale más simple (D-ML7). Se reusan las lecciones de alarmas: 7 días de evaluación como máximo, 0 no es lo mismo que "sin dato" |
| ML-037 | **Labs solo para el examen (fuera de prod)** | Endpoint en tiempo real, Serverless Inference, Clarify, Feature Store, tuning automático. **Se crean y se borran el mismo día**, con un runbook y un `make ml-lab-clean` que verifica que no quedó nada. Nada de esto entra a Terraform de prod |

**G3 — puerta de la Fase 3:** 14 noches seguidas en verde en la nube (como G4 de Uruguay), con los
resultados de la nube iguales a los locales sobre el mismo snapshot.

---

# Fase 4 — Guatemala y el cruce entre países

| ID | Qué | Notas |
|---|---|---|
| ML-040 | **Santa Lucía en el formato de `sorteos.core`** | Una tabla larga con `country = 'GT'`. Separa los números **sorteados** de los premios **derivados**. El rango de billetes de cada sorteo (ordinario o extraordinario) va en `game_rules`, con su fuente |
| ML-041 | **Vendido frente a no vendido** — la prueba más fuerte de Guatemala | Si el sorteo es justo, `P(vendido \| premio mayor)` = `P(vendido \| premio sorteado común)`, sin necesidad de conocer las ventas. Exacta de Fisher o regresión logística por tipo de premio, con el sorteo como bloque |
| ML-042 | **La batería de ML-012 y el C2ST sobre Guatemala** | Con la potencia que den unos 120 sorteos (ML-013 la calcula antes) |
| ML-043 | **Control negativo GT × UY** | La correlación entre los números de Guatemala y de Uruguay del mismo día **tiene que dar cero**. Si la metodología encuentra "señal" ahí, el error es de la metodología. Es la diapositiva más convincente de la charla |
| ML-044 | **Modelo bayesiano jerárquico (opcional)** | PyMC. Comparte entre países la distribución previa de "qué tan grande es el sesgo típico de un bolillero físico", así Uruguay (mucho dato) informa a Guatemala (poco). Es la única forma legítima de que un país "ayude" al otro. Antes hay que verificar si los dos usan bolilleros por dígito |
| ML-045 | **Vendedores y geografía, con cuidado** | Sin el volumen de ventas, un vendedor "con suerte" probablemente solo vende mucho. Se miran solo cambios dentro de un mismo vendedor a lo largo del tiempo, y se publica agregado (regla 9) |
| ML-046 | **Santa Lucía en el pipeline de SageMaker** | Una vez que ML-040..043 estén validados en local, entra al mismo Processing job |

---

# Fase 5 — Resultados, charla y certificación

| ID | Qué | Notas |
|---|---|---|
| ML-050 | **Reporte de resultados** | Una página pública con cada hipótesis: esperado, observado, potencia y si es exploratoria o confirmatoria. Incluye lo que no se pudo concluir |
| ML-051 | **La charla (AWS Community Group)** | Hilo propuesto: el problema → cómo se pone a prueba la aleatoriedad → el simulador y la calibración → C2ST → el control negativo GT × UY → la arquitectura en SageMaker → lo que salió mal (Lake Formation, costos, horas mal tipeadas) → conclusiones. Demo: el Processing job y la tabla en Athena |
| ML-052 | **Preparación de MLA-C01** | Repasar el mapa de abajo, hacer los labs de ML-037 y practicar con exámenes de prueba |

---

## Mapa a la certificación MLA-C01

Dominios del examen. Los pesos son los publicados en la guía oficial; **hay que reconfirmarlos en
ML-052**, porque AWS los actualiza.

| Dominio | Peso | Lo cubren |
|---|---|---|
| 1. Preparación de datos para ML | 28 % | ML-010, ML-011, ML-020 · Glue Catalog, Athena, Lake Formation (ya existen) · Feature Store (ML-037) |
| 2. Desarrollo de modelos | 26 % | ML-021, ML-022, ML-023, ML-035 (RCF, algoritmo incluido) · tuning (ML-037) · métricas y validación temporal |
| 3. Despliegue y orquestación de flujos de ML | 22 % | ML-031 (ECR), ML-032 (Processing), ML-033 (Pipelines), Batch Transform (ML-035) · endpoints y Serverless Inference (ML-037) · Terraform |
| 4. Monitoreo, mantenimiento y seguridad | 24 % | ML-030 (IAM mínimo, LF, Budgets), ML-034 (Registry), ML-036 (Model Monitor, alarmas) · Clarify (ML-037) |

---

## Decisiones abiertas (se responden al abrir su fase)

| # | Pregunta | Opciones | Recomendación |
|---|---|---|---|
| D-ML5 | ¿Dónde vive la infraestructura de ML? | a) `terraform/ml/`, stack y estado propios · b) dentro de `terraform/uy/` | **a**: el apply de ML nunca toca Uruguay, el mismo motivo por el que `terraform/uy/` se separó |
| D-ML6 | ¿Qué orquesta el job? | a) un paso en Step Functions · b) SageMaker Pipelines | **b**: es lo que pregunta el examen, y dispararlo con EventBridge deja la máquina de Uruguay intacta |
| D-ML7 | ¿Cómo se monitorea la deriva? | a) Model Monitor · b) un Processing propio | **a** si su costo en batch es razonable (ML-030 lo mide); si no, **b** |
| D-ML8 | ¿Dónde se publica el reporte de ML-050? | a) GitHub Pages, junto al diagrama · b) un artifact | **a**: queda en el mismo sitio que el resto del portafolio |

---

# Después de v1 (diferido)

| ID | Tema | Notas |
|---|---|---|
| ML-L1 | Otros países | Llega con UL4 de Uruguay: la misma batería, sin tocar el núcleo |
| ML-L2 | Kini histórico (2006–2013) | El dato ya está en el bronce (UL2). Más historia para la batería |
| ML-L3 | Demo en Databricks | Free Edition sobre un export en Parquet: el mismo paquete con MLflow. Solo como comparación para la charla o el CV |
| ML-L4 | Pozos en términos reales | Depende de UL5 (IPC del INE) |

---

# Tracker

| ID | Tema | Estado | PR |
|---|---|---|---|
| ML-000 | Este roadmap | **en revisión** (2026-11-18) | — |
| ML-001 | Plan de análisis pre-registrado | todo | — |
| ML-002 | Entorno local y paquete `sorteos.ml` | todo (después de #175) | — |
| ML-010 | Snapshot de datos | todo | — |
| ML-011 | Simulador del modelo nulo | todo | — |
| ML-012 | Batería clásica | todo | — |
| ML-013 | Análisis de potencia | todo | — |
| ML-014 | Detección de cambios | todo | — |
| ML-015 | Bolilla extra del 5 de Oro (01–44) | todo | — |
| ML-016 | Corrida confirmatoria | todo | — |
| G1 | Puerta de la Fase 1 | — | — |
| ML-020 | Variables por sorteo | todo | — |
| ML-021 | C2ST | todo | — |
| ML-022 | Prueba de predictibilidad | todo | — |
| ML-023 | Detector de anomalías | todo | — |
| ML-024 | Pozos y ganadores | todo | — |
| G2 | Puerta de la Fase 2 | — | — |
| ML-030 | Diseño, seguridad y costos en AWS | todo | — |
| ML-031 | Contenedor en ECR | todo | — |
| ML-032 | Processing job | todo | — |
| ML-033 | Orquestación | todo | — |
| ML-034 | MLflow y Model Registry | todo | — |
| ML-035 | RCF frente a Isolation Forest | todo | — |
| ML-036 | Monitoreo | todo | — |
| ML-037 | Labs del examen (fuera de prod) | todo | — |
| G3 | Puerta de la Fase 3 (14 noches) | — | — |
| ML-040 | Santa Lucía en `sorteos.core` | todo | — |
| ML-041 | Vendido frente a no vendido | todo | — |
| ML-042 | Batería y C2ST sobre Guatemala | todo | — |
| ML-043 | Control negativo GT × UY | todo | — |
| ML-044 | Modelo jerárquico (opcional) | todo | — |
| ML-045 | Vendedores y geografía | todo | — |
| ML-046 | Santa Lucía en SageMaker | todo | — |
| ML-050 | Reporte de resultados | todo | — |
| ML-051 | La charla | todo | — |
| ML-052 | Preparación de MLA-C01 | todo | — |
