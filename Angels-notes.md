# Notas De Angel
> Estas son mis notas personales, es una verificacion como Qa haciendo algo como una "Ingenieria Inversa" del proyecto, a este punto la fase de "Data Engineering" fue concluida de forma exitosa, ahora toca revalidar todo lo que se ha trabajado y verificar si mis decisiones tecnicas son justificables o necesitan una mejora o un mejor juicio con el objetivo de "Defender mi Tesis" asi como no solo confiar en lo que me ha sugerido una AI. 

## Parada 1 — Las fuentes (2026-11-25)

### 1. ¿Qué pasa si mañana el sitio cambia su HTML? ¿Quién se entera primero y cómo?

**Respuesta corta:** "Me entero yo, por correo o por un issue de GitHub, y casi siempre antes de que haya datos malos. Un cambio de HTML no puede entrar en silencio: o falla la extracción, o la fila va a cuarentena, o el gate de calidad bloquea el oro. En los tres casos el oro de la semana anterior sigue publicado."

### 2. ¿Es legal y ético scrapear estos sitios? ¿Qué hiciste para ser un buen visitante?

**Respuesta corta:** "No tengo una conclusión legal, porque no soy abogado, y lo digo así. Lo que sí controlo es el comportamiento: datos públicos, volumen mínimo, me identifico, no pido dos veces lo mismo y no bajo datos personales aunque estén publicados."

### 3. ¿Por qué Uruguay no necesita proxy y Guatemala sí?

**Respuesta corta:** "Porque el sitio de Guatemala está detrás de Cloudflare y solo acepta IPs residenciales guatemaltecas, y una Lambda en us-east-1 sale con IP de datacenter de EE. UU. El sitio de Uruguay no tiene ese bloqueo: le responde directo a AWS."

### 4. ¿Cómo sabes que no te falta ningún sorteo?

**Respuesta corta:** "En Uruguay lo sé porque mantengo un calendario de lo que debería existir y una alarma por cada hueco sin explicar. En Guatemala solo lo puedo comprobar desde 2024: Santa Lucía publica cada año una imagen con el calendario de sorteos (fecha, tipo y número), y tengo las de 2024, 2025 y 2026 en `images/`. Para los años anteriores no hay forma de saberlo: la lotería no guarda sus sorteos viejos en internet, y la única fuente sería el periódico que publica la lista, a Q47 (unos 8 dólares) por página en PDF. Así que el historial empieza donde empieza, y lo que sí controlo es no perder sorteos de aquí en adelante: alarmas si la corrida falla, un dead-man de 7 días y recuperación manual por el id del sitio."

**Nota (2026-11-25):** el Internet Archive (Wayback Machine) tampoco sirve. loteria.org.gt bloquea todas las IPs que no son de Guatemala, así que sus rastreadores nunca pudieron guardar esas páginas. Lo intenté yo mismo. Por eso es probable que mi dataset sea hoy la copia más vieja que existe de los resultados completos de esta lotería.

## Parada 2 — Los scrapers y la extracción (2026-11-25)

### ¿Qué haría falta para agregar un tercer país?

**Respuesta corta:** "Un paquete nuevo con lo que es propio del sitio, y un stack de Terraform propio. Todo lo que no depende del país ya está en `core/`. Lo caro no es el código: es investigar cómo publica el sitio."

- **Ya se reutiliza (`src/sorteos/core/`):** el cliente cortés, el manifiesto (SQLite local y DynamoDB), el bronce, los esquemas de plata con `country` + `operator` + `game` (D1) y `currency` (D6), el detector de huecos, el oro atómico, los montos, las métricas EMF y la reconciliación.
- **Lo nuevo (`src/sorteos/<iso>/`, con `uy/` de plantilla):** primero la investigación (robots.txt, términos, qué devuelve una fecha sin sorteo, calendario, datos personales); después `privacy.py` (blocklist obligatoria, aunque sea vacía), `sources.py` + `site.yaml` + `games/*.yaml`, `classify.py` (lo más propio de cada sitio), parsers, suites de GX, `calendar_events` y `dq_flags`.
- **Infraestructura (patrón UY-041):** stack `terraform/<iso>/` con su propia key de estado, prefijo `<iso>/` en el mismo bucket, `lottery_<iso>_db` + workgroup, tabla de manifiesto, Scheduler con la zona horaria del país y alarmas al mismo SNS.
- **Lo que reconozco:** las Lambdas viven en `uy/`, así que un país nuevo las copiaría; antes habría que subir lo común a `core/`. Y Guatemala no usa este marco (sigue en `src/loteria/`), así que en rigor sería el segundo país sobre `sorteos/`, no el tercero.

### ¿Por qué un manifiesto en DynamoDB y no "listar S3 y ver qué falta"?

**Respuesta corta:** "Porque S3 solo dice qué archivo existe, no qué pregunté ni qué me respondieron. Un día sin sorteo no deja nada en S3, y si mirara solo S3 lo volvería a pedir cada noche para siempre. El manifiesto recuerda la respuesta, no solo el archivo."

### ¿Qué pasa si la Lambda muere a mitad de la corrida?

**Respuesta corta:** "Nada se pierde y nada queda a medias publicado. Cada paso escribe de forma que repetirlo da el mismo resultado, lo que quedó pendiente se anota antes de hacerlo, y el oro solo cambia cuando todo está listo. La ejecución falla, suena la alarma, y la corrida siguiente termina el trabajo sola."

### ¿Por qué tu scraper de Guatemala reintenta a los 5, 15 y 35 minutos y no al segundo?

**Respuesta corta:** "Porque lo que falla no es mi código ni la red: es una rotación del proxy contra Cloudflare. Una rotación un minuto después cae en el mismo grupo de IPs y falla igual. Con minutos le doy tiempo a que cambie el grupo. Como la corrida es semanal y no hay nada esperando el dato, esperar 35 minutos no cuesta nada."

### ¿Cómo demuestras que el token del proxy no aparece en ningún log?

**Respuesta corta:** "Con tres cosas: el código lo enmascara antes de que salga, hay tests que fallan si deja de hacerlo, y busqué el token en los logs reales sin encontrarlo. Los tests prueban el futuro; la búsqueda prueba el pasado."

### Rotación del token de scrape.do (2026-11-26)

**Respuesta corta:** "Roto el token del proxy justo después de la corrida semanal, cuando más lejos estoy del próximo uso. Cambio solo esa llave del secreto, compruebo sin mostrar el valor que AWS tiene el nuevo, actualizo GitHub, corro el canario a mano y confirmo que el viejo quedó inactivo. Si algo sale mal, la versión anterior sigue guardada en Secrets Manager."

- **Cuándo:** el jueves, después de la corrida de las 18:00 UTC (salió verde a las 18:10). El próximo uso era el canario del miércoles siguiente, así que tenía casi una semana de margen.
- **Cómo, sin que el token se vea:** el token vivió en un archivo temporal fuera del repo. El JSON nuevo se armó con `jq --rawfile` y se revisó comparando solo nombres de llaves y largos. Después, `put-secret-value` y una comparación final que solo imprime ✓. La versión vieja quedó como `AWSPREVIOUS`.
- **Evidencia:** canario manual en verde (15 tests pasaron, 20 créditos); el token nuevo está activo y el viejo da `IsActive: false` con 0 créditos.
- **Falta:** ver la corrida del jueves 2026-12-03, la primera en que la Lambda usa el token nuevo.
- **Lo que aprendí:** un script sin shebang lo ejecuta `dash`, que no entiende `<<<`; y scrape.do no responde 401 con un token viejo, responde 200 con `IsActive: false`.

**Idea (2026-11-25):** Santa Lucía no tiene manifiesto. Usar los calendarios oficiales (`images/listado_sorteos_*.jpg`) como la lista de lo que debería existir, igual que Uruguay usa su calendario, sería una buena práctica que hoy no está implementada.

## Parada 3 — El data lake en S3 (2026-11-27)

### ¿Por qué un bucket con prefijos y no un bucket por capa?

**Respuesta corta:** "Porque con un solo dueño y este volumen, un bucket me da una sola política de protección, un solo versionado y un solo lifecycle, en vez de repetirlos por capa. IAM y Lake Formation ya trabajan por prefijo, así que el aislamiento lo pongo ahí. Lo partiría si hubiera varios equipos o datos regulados."

- **A favor:** el rol de purga solo puede tocar `gold/*` por IAM; Lake Formation registra `silver/` y `uy/silver/` por prefijo; Uruguay entró como `uy/` sin crear infraestructura nueva.
- **En contra, y lo reconozco:** un bucket por capa aísla mejor los daños, permite reglas distintas por capa (por ejemplo, versionar solo `raw/`) y separa los costos. La política ya necesita dos `Deny` y un `NotResource`: es la señal de que se está complicando.

### Si alguien con permisos de administrador borra `silver/` por error, ¿qué pasa?

**Respuesta corta:** "No puede: la política del bucket tiene un `Deny` explícito y en IAM un `Deny` siempre gana a cualquier `Allow`, aunque tenga `AdministratorAccess`. Y si primero cambiara la política, el versionado haría que el borrado solo deje marcas, y la versión anterior se puede restaurar. La última defensa es que `silver/` se puede regenerar desde `raw/`, que nunca se pisa."

- **Quién sí puede borrar:** root, el rol de purga de oro de Santa Lucía y la Lambda de oro de Uruguay. Un segundo `Deny` encierra a esta última dentro de `uy/gold/`.
- **El hueco que reconozco:** el admin no puede borrar, pero sí puede cambiar la política (`PutBucketPolicy` no está denegado). La protección es contra accidentes, no contra un admin malicioso. Y la política no está en Terraform: la aplica `scripts/00_inventory_and_protect.sh`.
- **Por qué se puede restaurar:** la regla de lifecycle `Delete-old-versions` expira las versiones viejas a los 30 días, pero `NewerNoncurrentVersions=1` guarda para siempre la más reciente. Quitar las marcas de borrado devuelve el archivo.
- **Lo que aprendí con el oro:** en un bucket versionado, `DeleteObject` no borra nada, solo pone una marca. La purga de oro "vaciaba" la carpeta pero Athena seguía viendo objetos y el CTAS fallaba con `HIVE_PATH_ALREADY_EXISTS` (2026-07-22). Para vaciar de verdad hay que borrar versiones y marcas por `VersionId`, con `s3:DeleteObjectVersion`.

### ¿Para qué Lake Formation, si ya tienes IAM?

**Respuesta corta:** "IAM decide qué llamadas a la API y qué objetos de S3 puede tocar alguien. Lake Formation decide qué bases, tablas, columnas o filas del catálogo puede ver, y le entrega a Athena credenciales temporales para leer S3. Hoy, con un solo usuario, aporta poco; vale la pena cuando haya varios consumidores, por ejemplo SageMaker leyendo solo oro."

- **Corrección mía:** Lake Formation no indexa los datos. El índice es el Glue Data Catalog, que se llena con crawlers, con Terraform o con un CTAS.
- **Se necesitan los dos:** una lectura falla si falta el permiso de Lake Formation o el de IAM (`lakeformation:GetDataAccess`).
- **Lo que costó:** el swap de oro necesitó tres arreglos de permisos, y un cambio de permisos no se nota hasta una corrida real.

### ¿Por qué Parquet y no CSV o JSON en plata?

**Respuesta corta:** "Porque es columnar, va comprimido y guarda el esquema con sus tipos dentro del archivo. Athena lee solo las columnas que pido y se salta bloques con las estadísticas min/max. A este volumen no me ahorra dólares, porque Athena cobra un mínimo de 10 MiB por consulta; lo que me da de verdad son los tipos."

- **Corrección mía:** la alternativa columnar es ORC, no "OCR".
- **Dónde sí uso JSON/HTML:** en `raw/`, porque ahí quiero la forma original de la respuesta, sin interpretar.
- **Lo que aprendí con los tipos:** una columna toda `None` se escribe con el tipo `Null` de Parquet y un `int` de Python como int64. Ambos rompen la lectura cuando la tabla declara otro tipo. CSV no me habría avisado: lo habría leído todo como texto.

### Hallazgos de la parada

- **`lambda-code-zip-prod` es el nombre del bucket, no de un archivo.** Adentro están los zips de las Lambdas y del job de Glue. Tiene versionado, bloqueo de acceso público y una regla que expira versiones viejas a los 90 días (PR-054).
- **El bucket simple** se creó para leer los datos sin particiones desde notebooks; nunca se usó en serio. Se retiró porque cada sorteo se escribía dos veces (*Fault A* de la auditoría de 2026-09-14) y se borró el 2026-10-22. Los notebooks pueden leer desde Athena.
- **`processed/` está muerto.** 267 objetos (1.8 MB) que nadie escribe desde PR-012, cuando el transformer pasó a `silver/`. Le cuelgan, todo fuera de Terraform: 2 tablas Glue (`premios_premios`, `sorteos_sorteos`), 2 crawlers sin schedule (última corrida 2025-12-14) y 3 ubicaciones en Lake Formation. Ningún código lo lee. PR-012 lo dejó "por precaución" y nadie volvió a revisarlo.
  - **Decisión:** retirarlo en un PR chico, en orden: crawlers → tablas → ubicaciones de Lake Formation → objetos (estos con root, por el `Deny`).
- **Tablas: Terraform vs crawler.** Yo recordaba que Uruguay estaba en Terraform y Santa Lucía en crawler, pero ya no es así: los esquemas de plata de los dos países están en Terraform (Santa Lucía desde PR-045.2, importado). La diferencia real está en las particiones: Santa Lucía las registra con un crawler (con el esquema bloqueado) y Uruguay usa *partition projection*, sin crawler. El oro, en los dos, lo crea el pipeline (CTAS o Lambda), no Terraform.
  - **Decisión:** medir *partition projection* para Santa Lucía en un PR aparte. Quitaría 2 crawlers y el paso de polling de Step Functions. Hay que medirlo antes porque `sorteo` es texto y un rango amplio haría que una consulta sin filtro revise miles de prefijos.

## Parada 4 — La transformación a plata (2026-11-27)

### ¿Por qué el transform de Santa Lucía corre en Glue Python Shell y no en Lambda?

**Respuesta corta:** "Por el peso de pandas, no por el volumen. El entorno con pandas medía unos 420 MB descomprimido y un zip de Lambda admite 250 MB, aunque uses layers. Glue Python Shell trae pandas incluido. El precio fue quedarme en Python 3.9, que es el máximo de Python Shell."

- **Corrección mía:** yo creía que Lambda era "demasiado" para tan poco volumen. Es al revés: con poco volumen Lambda sería más barata y arrancaría más rápido. Lo que la descartó fue el tamaño del paquete (`docs/challenges.md`, sección 7).

### ¿Qué son las columnas de linaje?

**Respuesta corta:** "Son cuatro columnas en cada fila de plata que dicen de dónde salió: qué corrida la escribió (`run_id`), cuándo (`ingested_at`), de qué archivo de `raw/` (`source_key`) y con qué versión del parser (`parser_version`). Con el `run_id` voy de una fila en Athena a su ejecución de Step Functions y a sus logs."

- **`run_id`:** es el nombre de la ejecución de Step Functions. Es NULL a propósito cuando la escritura no vino del pipeline, por ejemplo una corrida a mano.
- **`ingested_at`:** la hora en que el transformer escribió el archivo, en UTC y sin zona horaria.
- **Un solo lugar:** el contrato vive en `src/loteria/common/lineage.py`, así el que escribe, el que valida y el que lee no pueden desincronizarse.
- **Los archivos viejos:** 222 archivos son anteriores a estas columnas. Por eso el gate de calidad solo las exige cuando `parser_version >= 1`; si no, estaría en rojo desde el primer día con datos que están bien.

### ¿Qué clases de rechazo existen en la cuarentena y cuál dispara una alarma?

**Respuesta corta:** "Cinco, y la lista es cerrada a propósito: contar por texto libre no sirve. Tres son por línea y dos por archivo. Solo `unrecognised` dispara alarma, porque significa que el sitio cambió o que el parser tiene un hueco. Hay una segunda alarma para cuando no se pudo escribir la cuarentena misma."

| código | nivel | ¿se guarda? | ¿alarma? |
|---|---|---|---|
| `section_header` | línea | no, solo se cuenta (6.5% de las líneas: encabezados como "DOS MIL") | no |
| `orphan_vendor_line` | línea | sí | no |
| `unrecognised` | línea | sí | **sí** |
| `malformed_header` | archivo | sí | no |
| `unexpected_key` | archivo | sí | no |

- **La otra alarma:** si falla la escritura de la cuarentena, plata está bien pero se perdió el registro de lo descartado.
- **El umbral se midió:** `unrecognised` apareció una vez en 118 sorteos, así que la alarma suena más o menos una vez al año. Una alarma que sonara cada semana se silenciaría en un mes.
- **Hoy (2026-11-27):** `quarantine/` está vacío en los dos países.

### ¿Por qué el esquema de plata está en Terraform y no lo decide el crawler?

**Respuesta corta:** "Porque el crawler no podía evolucionar el esquema. Las columnas de linaje se escribían en el Parquet pero Athena no las veía. Y abrir el crawler era peor: inferiría los tipos de los datos en una tabla de la que dependen siete consultas de oro. Con Terraform el esquema es un contrato revisado en un PR, no una adivinanza."

- **Los tres ajustes que se suman:** `UpdateBehavior: LOG` (detecta el cambio y solo lo anota), `CRAWL_NEW_FOLDERS_ONLY` (nunca vuelve a mirar las particiones existentes) e `InheritFromTable` (una partición nueva hereda el esquema de la tabla, no el de sus archivos).
- **Corrección mía:** yo pensaba que era por trazabilidad y escalabilidad. La trazabilidad es un beneficio; la razón fue que el crawler escondía las columnas nuevas.
- **El contrato se prueba:** un test verifica que las columnas declaradas en Terraform coincidan con las de Python.
- **El crawler sigue:** ahora solo registra particiones nuevas, con el esquema bloqueado.

### ¿Por qué la Lambda de plata de Uruguay es una imagen y la de fetch un zip? (D29)

**Respuesta corta:** "Por tamaño. Las dependencias de silver miden 222 MB, y solo `pyarrow` son 156 MB. El límite de un zip es 250 MB, así que quedaban 28 MB de margen, que una versión nueva de `pyarrow` se puede comer. Una imagen admite 10 GB. Fetch solo usa `requests`, `beautifulsoup4` y `pyyaml`: un zip es más simple, sin ECR ni build de imagen."

- **Corrección mía:** el zip no es zip por estar en S3. Es zip porque es chico; si fuera grande, también sería imagen.

### ¿Por qué D17 reescribe el año entero y no hace append?

**Respuesta corta:** "Porque Parquet no tiene upsert. Con append, repetir una corrida duplica filas; reescribir el año da siempre el mismo resultado. Y hay correcciones: los pozos del 5 de Oro que llegan tarde se vuelven a pedir hasta por 14 días, y esas filas hay que reemplazarlas, no sumarlas. Reescribir un año son unos 650 sorteos y unos 12 segundos."

- **Además:** un append diario dejaría cientos de archivos chicos por año, y Athena lee peor muchos archivos chicos que pocos grandes.
- **Qué es un año "tocado":** uno con al menos un sorteo que cambió en la corrida. Un día normal toca un año; la primera semana de enero, dos.

### ¿Qué es una dead letter queue y por qué no hay ninguna?

**Respuesta corta:** "Es una cola, normalmente de SQS, donde AWS deja un evento que falló después de agotar los reintentos, para no perderlo. Solo existe para invocaciones asíncronas. Aquí Step Functions llama a las Lambdas de forma síncrona: si una falla, falla la ejecución y suena la alarma. No hay ningún evento que se pueda perder en silencio."

- **Está documentado:** el chequeo de checkov que pide una DLQ (`CKV_AWS_116`) está suprimido en el Terraform con ese motivo escrito, no ignorado.

### ¿Qué pasa si el parser se encuentra con un formato nuevo?

**Respuesta corta:** "No se pierde nada y nada entra a medias. En Santa Lucía, la línea o el archivo van a cuarentena, la corrida sigue con el resto y suena la alarma si es `unrecognised`. En Uruguay, el sorteo va entero a cuarentena. En los dos casos el original sigue en bronce, así que cuando arreglo el parser vuelvo a parsear sin pedirle nada de nuevo al sitio."

- **Santa Lucía:** antes de PR-044.2, un encabezado roto tumbaba la corrida de toda la semana; ahora ese archivo va a cuarentena y el resto se escribe.
- **El `except` es angosto a propósito:** captura solo `ValueError` ("el dato no es lo que esperaba"). Un error de S3 o un bug sigue haciendo fallar la corrida, en vez de disfrazarse de dato malo.
- **Uruguay:** mientras haya algo en cuarentena, `draw_gaps` no se reescribe; si no, ese sorteo parecería un hueco del calendario.

### ¿Por qué Glue para Guatemala y Lambda para Uruguay?

**Respuesta corta:** "Por historia, no por principio. Guatemala se construyó cuando pandas no entraba en un zip de Lambda y la salida fue Glue. Uruguay se diseñó después, con imágenes de contenedor, que me dan Python 3.12 y espacio para `pyarrow`. Si empezara hoy, los dos serían Lambda con imagen. Migrar Guatemala no se justifica mientras funcione y cueste centavos."

- **Uruguay también usa Glue:** pero solo para Great Expectations (Glue 5.0), porque GX 1.x no corre en Python 3.9.

### ¿Cómo sabes qué versión del parser produjo cada fila?

**Respuesta corta:** "Cada fila lleva `parser_version`, junto con `source_key` y `run_id`: sé qué versión, de qué archivo y en qué corrida. La debilidad es que la versión se sube a mano en `lineage.py`. Si alguien cambia el parser y se olvida de subirla, la columna miente."
