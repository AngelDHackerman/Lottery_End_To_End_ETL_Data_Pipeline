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
