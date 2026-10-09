/* Arquitectura Lotería Santa Lucía — datos del diagrama.
   Todo lo que describe la arquitectura vive aquí; el render y la interacción
   viven en diagram.js. Para actualizar el diagrama, normalmente solo se toca
   este archivo. Se expone como window.DIAGRAM_DATA.

   Verificado contra la cuenta 913524903233 el 2026-09-25: definición de la
   máquina de estados, cron de EventBridge, argumentos de los dos jobs de Glue,
   env del Lambda extractor, política del Lambda de gold, grants de Lake
   Formation, alarmas, tablas del catálogo y conteos de objetos por capa.

   Re-leído el 2026-09-27, tras borrar las 9 tablas __stg_ huérfanas: tablas del
   catálogo (20 → 11), ubicación de las 7 gold, particiones de geo_winnings,
   objetos por tabla bajo la generación viva, args del job de Glue, env del
   extractor, política de gold-purge y política del bucket particionado. Lo que
   NO se volvió a leer ese día: alarmas, grants de Lake Formation y la definición
   de la máquina de estados — siguen fechados al 25.

   Re-leído el 2026-10-04, tras aplicar PR-045.2: tablas y vistas del catálogo
   (12 + 2), columnas y particiones de las dos silver, conteos de raw/silver/gold,
   generación viva de Gold, veredicto del gate del 1 oct, estado de las 9 alarmas,
   el Retry del extractor y la descripción de la alarma de ejecución (los dos
   siguen sin arreglar) y el conteo del bucket simple (347).

   Re-leído el 2026-10-08, tras la corrida programada que trajo el 3138: conteos
   de raw/silver/quarantine/gold, el linaje del 3138 en el Parquet y en las dos
   vistas, los contadores del parser y las dos alarmas de cuarentena. */
(function (global) {
  "use strict";

  /* Marcos de contexto: plano de control, cuenta AWS, VPC. */
  const ZONES = [
    {x:24,  y:126, w:352, h:300, cls:"gh",  label:"PLANO DE CONTROL · GITHUB ACTIONS", color:"var(--soft)"},
    {x:400, y:126, w:976, h:600, cls:"aws", label:"CUENTA AWS · 913524903233 · us-east-1", color:"var(--ink)"},
    {x:420, y:640, w:936, h:66,  cls:"vpc", label:"", color:"var(--off)"}
  ];

  /* Nodos. st: ok | pend | bad | off. Los de w:0 son marcadores sin caja. */
  const NODES = [
    {id:"site", x:540, y:24, w:300, h:60, st:"ok", t:"loteria.org.gt", s:["tras Cloudflare · vía scrape.do"],
     title:"El río — la fuente", desc:"El sitio oficial de la Lotería Santa Lucía. Es la única fuente: una vez que un sorteo caduca, el dato desaparece del sitio para siempre.",
     kv:{"Acceso":"scrape.do con geoCode=GT&super=true","Costo":"10 créditos por request (eran 25)","Al mes":"~175 de 1000, entre corridas y canary","Lo tocan":"el canary (mié) y el extractor (jue)"},
     warn:{k:"b",t:"El perfil del proxy no es una constante, es una negociación viva. En agosto hizo falta AÑADIR render=true para pasar Cloudflare; el 24 de septiembre ese mismo parámetro era la causa del 502 — ocho fallos idénticos a los 57,5 s, y geoCode=GT&super=true sin render respondió 200 en 9,7 s al primer intento. Lo que aguantó en los dos incidentes es GT + super: ese es el piso, render es la perilla. Y como scrape.do no cobra los fallos, probar variantes de un perfil roto es gratis: esa es la técnica de diagnóstico, antes que razonar desde la documentación."}},

    {id:"ci", x:44, y:166, w:312, h:74, st:"ok", t:"ci.yml · 8 jobs", s:["lint · test · build reproducible","tf-validate ×2 · checkov · trivy · bandit"],
     title:"CI — la prueba de presión", desc:"Corre en cada pull request y en cada push a master. Ocho jobs deliberadamente independientes, para que un cambio de Terraform no espere al de Python y viceversa. Son nueve check runs: tf-validate es una matriz sobre terraform/ y terraform/bootstrap/.",
     kv:{"Credenciales AWS":"ninguna","Terraform":"init -backend=false","checkov":"bloqueante, con baseline","trivy":"no bloqueante → pestaña Security","Job nuevo":"build-reproducible (PR-046)","Cobertura":"gate en 98"},
     warn:{k:"p",t:"build-reproducible hace dos cosas que ningún test unitario puede: recompila el lock y falla si alguien tocó requirements sin correr make lock, y construye el layer DOS veces en el mismo runner exigiendo que los dos zips sean byte a byte idénticos. Existe porque cada plan de Terraform venía contaminado por una transitiva suelta que reemplazaba el layer cualquier día."}},

    {id:"canary", x:44, y:262, w:312, h:74, st:"ok", t:"scraper-canary.yml", s:["miércoles 18:00 UTC","abre un issue si cambia el HTML"],
     title:"Canary — 24 h de ventaja", desc:"Golpea el sitio real un día antes que el pipeline y comprueba que los selectores siguen encontrando lo que el extractor espera. Si el sitio cambió, abre un issue con el selector que falló.",
     kv:{"Cuándo":"miércoles 18:00 UTC","Por qué el miércoles":"24 h antes del pipeline","Créditos":"el único workflow que los gasta","Guardas":"selectores + perfil del proxy"},
     warn:{k:"p",t:"El canary duplica a mano el perfil del proxy, porque no puede importar scraping.py (llama a get_secrets() en el módulo y Actions no tiene AWS). Esa duplicación estaba custodiada solo por un comentario pidiéndole al siguiente lector que mantuviera dos archivos en sintonía. Desde PR-031.2 un test lee los defaults del código fuente y falla si derivan — sin él, este PR habría dejado al canary probando un request que producción ya no hace."}},

    {id:"owner", x:44, y:356, w:312, h:56, st:"pend", t:"El owner, a mano", s:["make deploy → build · apply · upload"],
     title:"El puente humano", desc:"La única vía real entre GitHub y la cuenta de AWS. Terraform no gestiona los objetos de código en S3, así que construir y subir los zips es un paso manual — pero desde PR-039 es un solo comando, y eso cerró la deriva silenciosa de los artefactos de Glue.",
     kv:{"Comando":"make deploy = build → apply → upload-glue","Artefactos":"lambda_layer.zip · lambda_package.zip · lottery_transformer.zip","Del gate":"loteria_silver_dq.py · loteria_dq_lib.zip","Destino":"s3://lambda-code-zip-prod","Al día":"4 oct 2026 · PR-045.2 (imports + make deploy + make lineage-views)"},
     warn:{k:"p",t:"Ningún target del Makefile imprime ya TODO. Antes siete lo hacían —deploy, lint y fmt entre ellos—, así que un README que prometiera «5 comandos para desplegar» o mentía o rodeaba al Makefile, lo cual plantea por qué existe el Makefile."}},

    {id:"eb", x:424, y:158, w:180, h:56, st:"ok", t:"EventBridge", s:["cron(0 18 ? * THU *)"],
     title:"El disparador semanal", desc:"Una sola regla de cron. Arranca la máquina de estados los jueves a las 18:00 UTC (12:00 en Guatemala).",
     kv:{"Regla":"lottery-etl-weekly-trigger-prod","Cuándo":"jueves 18:00 UTC","Estado":"ENABLED"},
     warn:{k:"p",t:"Se movió del lunes al jueves: los sorteos del sábado dejan el sitio tras una sala de espera de Cloudflare durante días, y una corrida el lunes caía justo ahí. El jueves es el punto tranquilo de la semana."}},

    {id:"sfn", x:628, y:158, w:236, h:56, st:"ok", t:"Step Functions", s:["lottery-etl-pipeline-prod · 9 estados"],
     title:"El orquestador", desc:"La máquina de estados que conduce todo el pipeline: decide el orden, reintenta, corta el paso a Gold si la calidad falla, y desde el 25 de septiembre publica cada tabla gold con un swap en vez de borrarla y rehacerla.",
     kv:{"Nombre":"lottery-etl-pipeline-prod","Estados":"9 · el gate entre los crawlers y Gold","Logging":"ALL, con datos de ejecución","Rol":"sfn-lottery-execution-role-prod","Última corrida":"1 oct 2026 18:00 UTC · SUCCEEDED (programada)","Duración":"10m31s de punta a punta"},
     warn:{k:"p",t:"La corrida programada del 24 de septiembre murió en el extractor por el 502 de Cloudflare. Lo que siguió fueron cuatro corridas a mano esa noche: cada una llegó un estado más lejos que la anterior porque cada una destapó un permiso distinto. La quinta —verify-partitions— pasó entera. Ese es el único motivo por el que el swap está verificado hoy."}},

    {id:"tfstate", x:1140, y:158, w:216, h:56, st:"ok", t:"Estado de Terraform", s:["S3 + lock DynamoDB"],
     title:"Estado remoto", desc:"El estado de Terraform vive en S3 con bloqueo en DynamoDB. El estado legacy se perdió una vez y hubo que reconstruirlo importando 67 recursos a mano.",
     kv:{"Bucket":"loteria-tf-state-913524903233","Lock":"loteria-tf-locks","Versionado":"sí, + prevent_destroy"},
     warn:{k:"p",t:"No todo lo que gobierna la cuenta está en este estado. El grant de Lake Formation ALTER a nivel de base de datos se hizo fuera de banda: ningún plan iba a mostrar nunca que faltaba el de las tablas. Un recurso que no está en el estado es un recurso sobre el que Terraform no puede avisarte."}},

    {id:"extract", x:424, y:252, w:172, h:84, st:"ok", t:"Extractor", s:["Lambda · python","guard sobre silver/","escribe raw/"],
     title:"La toma de agua", desc:"Lambda que scrapea el sorteo de la semana a través del proxy y sube el .txt crudo. Antes de scrapear comprueba si el sorteo ya existe — y desde PR-035.1 lo comprueba donde el transformer escribe de verdad.",
     kv:{"Función":"lottery-extractor-prod","Rol":"lottery-lambda-exec-roleprod","Guard":"silver/sorteos/ (era processed/, muerto desde 2025)","Fecha del sorteo":"regex anclado \\d{2}/\\d{2}/(\\d{4})\\b","VPC":"ninguna — corre fuera"},
     warn:{k:"b",t:"El Retry de RunExtractorLambda no cubre el fallo que de verdad ocurre. Su ErrorEquals lista solo faltas de transporte —ReadTimeout, ConnectionError y cuatro Lambda.*— y un 502 del proxy llega como el ValueError de fetch_via_proxy. La corrida del 24 de septiembre tuvo un solo intento. Anotado en PR-031.2, sin arreglar: no habría salvado una caída de ocho fallos, pero el Retry dice que protege algo que no protege."}},

    {id:"transform", x:612, y:252, w:172, h:84, st:"ok", t:"Transformer", s:["Glue pythonshell 3.9","1 DPU · .sync","raw → silver + quarantine"],
     title:"La planta de tratamiento", desc:"Job de Glue que parsea el .txt, separa cabecera y cuerpo, limpia con pandas y escribe Parquet particionado por año y sorteo. Desde PR-041.2 escribe en un solo sitio: la copia plana al bucket simple ya no existe ni como argumento.",
     kv:{"Job":"lottery-transform-prod","Runtime":"Python Shell 3.9 (el techo)","Capacidad":"1 DPU","Salida":"silver/{sorteos,premios}/","Argumentos":"RAW_PREFIX · PARTITIONED_BUCKET · el secreto","Linaje":"run_id · ingested_at · source_key · parser_version (PR-045.1)","Rechazos":"contados y clasificados; los raros van a quarantine/ (PR-044)"},
     warn:{k:"p",t:"Los dos defectos de la auditoría que vivían aquí —044, filas descartadas sin registro, y 045, Parquet sin ingested_at ni run_id— quedaron VERIFICADOS el jueves 8 de octubre con el 3138, el primer sorteo que pasó por su código: la Parquet nueva trae las cuatro columnas con el nombre de la ejecución como run_id, y el log trae lines_total 1047 / lines_parsed 967 / lines_rejected 80 —las 80 encabezados de millar— con rejected_unrecognised en 0 y quarantined en 0. Tardó once días desde el deploy porque el 3137 se ingirió horas antes y la corrida del 1 de octubre no tenía nada nuevo que parsear —los sorteos son los sábados—. Y Python Shell solo ofrece 3.6 y 3.9: ese techo es la razón de que el gate de calidad tenga que ser un job Spark aparte."}},

    {id:"crawlers", x:800, y:252, w:172, h:84, st:"ok", t:"Crawlers ×2", s:["Parallel + polling real","LastCrawl.MessagePrefix","registran silver"],
     title:"El registro en el catálogo", desc:"Dos crawlers en paralelo que registran las particiones nuevas de silver en el catálogo de Glue, para que Athena pueda verlas. Son los únicos crawlers que quedan: gold nunca pasa por aquí. Desde PR-045.2 ya no deciden el esquema —las dos tablas silver están declaradas en Terraform— y su único trabajo es registrar la partición de la semana, que hereda el esquema declarado.",
     kv:{"Crawlers":"lottery-premios-silver-crawler · lottery-sorteos-silver-crawler","Espera":"polling hasta completar"},
     warn:{k:"p",t:"startCrawler no tiene variante .sync: la tarea terminaba en cuanto la API aceptaba la llamada, no cuando el crawl acababa. Los CTAS de gold leían un catálogo viejo y la tabla salía sin el sorteo nuevo, en silencio. PR-026.1 lo arregló con un bucle de polling — y comprobando LastCrawl.MessagePrefix, no State==READY, que es READY también cuando el crawl anterior terminó hace una semana."}},

    {id:"dq", x:988, y:252, w:172, h:84, st:"ok", t:"Gate de calidad", s:["Glue 5.0 · Spark","28 expectativas","corta el paso a Gold"],
     title:"El laboratorio", desc:"Valida el Silver entero contra dos suites de Great Expectations ANTES de tocar Gold. Si una expectativa falla, Gold no se construye: el Catch de la máquina lleva a NotifyDQFailure y la alerta nombra la suite, la expectativa y la columna.",
     kv:{"Cadena":"RunSilverCrawlers → RunSilverDQ → PrepGold","Si falla":"Catch → NotifyDQFailure → SilverDQFailed","Último veredicto":"PASS · 8 oct 2026 18:06 UTC","Alcance":"sorteos 15 expectativas / 119 filas · premios 13 / 125 337","Duración":"95 s","Runtime":"Glue 5.0 / Python 3.11","Rol":"glue_dq_role — solo lectura","Timeout":"60 min (PR-033.1)"},
     warn:{k:"p",t:"Verificado en los DOS sentidos, que es lo que importa: una corrida validó el Silver real y otra, apuntada a un prefijo inexistente, falló diciendo «esto es un problema de cableado, no de calidad». Un gate que solo ha pasado es indistinguible de no tener gate. Ojo a lo que NO cubre: valida lo que llegó a Silver, no lo que el parser tiró por el camino — eso es el defecto 044, y por definición no hay fila que validar."}},

    {id:"gold", x:1176, y:252, w:172, h:84, st:"ok", t:"Gold", s:["Map · concurrencia 3","construye · swap · retira","7 tablas · 4 estados c/u"],
     title:"El embotellado — el swap, ya probado", desc:"Siete consultas CTAS de Athena construyen las tablas de negocio. Cada una se construye AL LADO de la publicada, en gold/<tabla>/run=<ejecución>/, y solo cuando Athena termina bien el Lambda mueve el puntero del catálogo con un único UpdateTable. Un CTAS que falla ya no cambia nada.",
     kv:{"Tablas":"draw_summary · winning_number_frequency · terminations · letters_distribution · geo_winnings · vendor_leaderboard · time_series","Lambda":"lottery-gold-purge-prod","Cadena":"PrepareGold → RunCTAS → PromoteGold → RetireGold","Concurrencia":"3 de 7 a la vez","Atómica desde":"21 sep 2026 · PR-042.1","Verificada":"25 sep — el swap · 27 sep — la retención","Retención":"conserva la viva + 1 (PR-042.2)","Generación viva":"run=ca65cf86… (programada del 1 oct)","Rollback":"run=verify_045_1_044_1_1790540548"},
     warn:{k:"p",t:"Cerrado el 27 de septiembre, y lo que costó cerrarlo es la parte que vale. Las generaciones muertas de las corridas fallidas del 24 NO eran borrables a mano: el Deny de PR-002 exime exactamente a la raíz de la cuenta y al rol del Lambda de gold —un Deny explícito de política de bucket no lo gana ningún Allow de IAM, ni AdministratorAccess— y el Lambda solo exponía prepare y promote. O sea que la basura de 042.1 no se podía limpiar hasta que existiera el mecanismo que la limpia. La corrida de verificación retiró 12 prefijos de un golpe y dejó gold/ en 39 objetos: 13 vivos, 13 del rollback y 13 de la disposición anterior al swap, que se conserva a propósito porque es el único rollback que no viene de una corrida fallida. Desde entonces lleva cinco corridas seguidas retirando limpio, y gold/ sigue en 39."}},

    {id:"s3p", x:424, y:400, w:620, h:96, st:"ok", t:"S3 · lottery-partitioned-storage-prod", s:[],
     title:"El lago", desc:"El bucket que sostiene las tres capas. Tiene versionado, una política que deniega el borrado a todo el mundo salvo la raíz de la cuenta, y prevent_destroy en Terraform. Desde PR-041.2 es el único bucket de datos que recibe escrituras.",
     kv:{"Prefijos":"raw/ · silver/ · quarantine/ · gold/ · sql/gold/","Raw":"119 archivos .txt","Silver":"119 sorteos y 125 337 premios en 238 Parquet","Quarantine":"vacío — su estado normal","Gold":"39 objetos · 13 vivos · 1,0 MB","Al día hasta":"Ordinario 3138 (sorteado el 3 oct) · ingerido el 8 oct, corrida programada","Protección":"versionado + Deny + prevent_destroy"}},

    {id:"s3s", x:1064, y:400, w:268, h:96, st:"off", t:"S3 · lottery-data-simple-prod", s:["sin escritor · sin lector · sin grant","347 objetos congelados","solo faltan los bytes"],
     title:"El tanque huérfano, ya desconectado", desc:"El transformer y el extractor escribían aquí una copia plana de cada Parquet y cada .txt. Tenía sentido cuando era la única forma de mirar los datos sin pelear con particiones Hive; hoy Athena lee las tres capas. El 20 de septiembre se apagaron las tres escrituras por bandera; el 25 se le quitó toda la configuración y el grant. Ya no queda nada que lo nombre salvo los bytes.",
     kv:{"Defecto":"A → PR-041 (último paso pendiente)","Escrituras":"detenidas el 20 sep 2026 (PR-041.1)","Configuración":"retirada el 25 sep 2026 (PR-041.2)","Contenido":"347 objetos · 540 versiones · 9 MB","Lectores":"ninguno — el grant de SageMaker ya apunta a silver/ y gold/","Borrado":"no antes del 20 oct 2026 (PR-041.3)"},
     warn:{k:"b",t:"Nada de aquí es único: los 115 .txt y los 116 Parquet tienen su contraparte en raw/ y silver/, así que borrarlo no pierde datos. Pero borrarlo no es una línea: la política Deny de PR-002 bloquea el borrado a todo principal salvo la raíz, y con versionado encendido un borrado normal solo deja delete markers. La espera de 30 días no es formalidad: CloudTrail de datos está apagado para este bucket, así que compra con tiempo lo que la evidencia no puede probar. Condición de aborto, comprobada el 20 oct: si el conteo ya no es 347, algo sigue escribiendo. El 3 de octubre seguían siendo 347, con dos de los cuatro jueves de la espera ya pasados."}},

    {id:"cat", x:424, y:536, w:290, h:72, st:"ok", t:"Glue Data Catalog", s:["lottery_santalucia_db","12 tablas + 2 vistas · 3 en Terraform"],
     title:"El catálogo", desc:"Las dos tablas silver están declaradas en Terraform desde PR-045.2 —importadas, no creadas, para no perder sus 118 particiones— y los crawlers solo les registran la partición nueva. Las siete gold las publica el swap: el CTAS crea una tabla de staging y el Lambda repunta la publicada con un UpdateTable. Dos vistas de Athena responden qué corrida escribió cada fila.",
     kv:{"Base":"lottery_santalucia_db","Total":"12 tablas + 2 vistas","Definidas en Terraform":"silver_sorteos_sorteos (14 col.) · silver_premios_premios (11 col.) · quarantine_rejects","Silver":"2, esquema en Terraform, particiones por crawler","Gold":"7, publicadas por el swap","Vistas":"silver_lineage · silver_lineage_runs (make lineage-views)","Linaje hoy":"2 corridas: la NULL (118 sorteos, anteriores al linaje) y la del 8 oct (3138: 1 sorteo, 890 premios)","Restos legacy":"premios_premios y sorteos_sorteos, de los crawlers de processed/"},
     warn:{k:"p",t:"Los crawlers nunca pudieron evolucionar el esquema: UpdateBehavior LOG, CRAWL_NEW_FOLDERS_ONLY y particiones InheritFromTable —cualquiera de las tres basta para esconder una columna nueva. En vez de aflojarlas, PR-045.2 movió el esquema a Terraform y convirtió esas tres opciones en la garantía: un crawler que no altera tablas no puede pelear con un esquema declarado. Lo que había que probar era que las 118 particiones viejas, con 10 columnas, se siguieran leyendo bajo la tabla de 14: el gate del 4 de octubre lo hizo sin error, y silver_lineage_runs devolvió exactamente lo mismo que antes del apply. Hoy dice una sola corrida con run_id NULL —la respuesta verdadera, no un hueco— y el 8 de octubre debería decir dos."}},

    {id:"athena", x:730, y:536, w:290, h:72, st:"ok", t:"Athena · lottery-wg", s:["startQueryExecution.sync","construye el staging, no lo publicado"],
     title:"El motor de consulta", desc:"Workgroup propio. La máquina de estados lanza cada CTAS aquí con la integración .sync, así que espera de verdad a que la consulta termine. Desde el swap, lo que el CTAS escribe es una tabla de staging: publicar es otra llamada, y de otro servicio.",
     kv:{"Workgroup":"lottery-wg","Resultados":"lottery-athena-results-prod","Escribe":"gold/<tabla>/run=<ejecución>/"},
     warn:{k:"p",t:"El staging vive DEBAJO del prefijo que la tabla publicada apuntaba, y Athena lee una ubicación de forma recursiva. Entre el primer CTAS y su promote, una consulta sobre la tabla vieja vería los archivos viejos Y los nuevos, y contaría doble. La ventana dura segundos, se cierra en el promote y ocurrió una sola vez —después la tabla apunta a una generación concreta, no al padre—, pero está escrita aquí porque nadie la habría deducido del diagrama."}},

    {id:"lf", x:1036, y:536, w:312, h:72, st:"ok", t:"Lake Formation + IAM", s:["dos puertas independientes","sobre la misma llamada"],
     title:"Los permisos del lago — las dos puertas", desc:"El acceso al catálogo no vive en un solo sitio. Una lectura necesita las dos cosas: el grant de Lake Formation y el permiso lakeformation:GetDataAccess en IAM. Y una escritura al catálogo también: arreglar una puerta no dice nada de la otra.",
     kv:{"Modo":"híbrido, con compatibilidad IAM","Del swap (LF)":"ALTER · DESCRIBE · DROP sobre ALL_TABLES","Del swap (IAM)":"UpdateTable + las acciones SINGULARES de partición","Aplicado":"24–25 sep 2026 · PR-042.3 y PR-042.4","Ojo":"los grants son aditivos"},
     warn:{k:"b",t:"La lección de la noche del 24, que costó dos corridas separadas. PR-042.3: el rol tenía ALTER, pero a nivel de BASE DE DATOS — que autoriza alterar la base, no las tablas de dentro. Dos grants, la misma palabra, distinto recurso. PR-042.4: la política listaba glue:BatchUpdatePartition y el código llama a batch_update_partition, pero Glue autoriza las APIs Batch por ítem, contra la acción SINGULAR. Cuando un AccessDenied nombra una acción, hay que leer QUÉ SERVICIO lo dijo: «Insufficient Lake Formation permission(s)» y «no identity-based policy allows» vienen de sitios distintos."}},

    {id:"cw", x:424, y:640, w:0, h:0, st:"ok", t:"", s:[]},

    {id:"obs", x:424, y:756, w:440, h:72, st:"ok", t:"CloudWatch", s:["9 alarmas · dashboard · retención","conteo de objetos por capa"],
     title:"Observabilidad", desc:"Nueve alarmas: ejecución fallida, sin éxito reciente, errores del extractor, Glue fallido, crawler que no arrancó, scrape.do fallido, retención de Gold fallida (PR-042.2) y las dos de cuarentena (PR-044.2): líneas no reconocidas, y el escritor de cuarentena fallando. Más un dashboard y una Lambda horaria que publica el número de objetos por capa. Las nueve están en OK. Las dos de cuarentena todavía no han visto pasar un solo sorteo por el código que vigilan.",
     kv:{"Alarmas":"9 (la cuenta tiene 13: 4 son de otro proyecto)","Estado":"las 9 en OK · 3 oct 2026","Emisor":"lottery-object-count-prod (horaria)","Retención":"sobre los log groups compartidos de Glue","Del gate":"/aws-glue/jobs/loteria-silver-dq-prod"},
     warn:{k:"b",t:"La séptima alarma no se parece a las otras seis: RetireGold se traga sus propios fallos por diseño, así que la ejecución reporta SUCCEEDED, ExecutionsFailed queda en cero y ninguna métrica de servicio registra nada. Cuelga de un filtro que busca un token literal en el log del Lambda — lo que convierte esa línea de log en una interfaz: si alguien la reescribe, no falla nada y la alarma deja de saltar para siempre. Un test compara la constante de Python contra el patrón del .tf por eso mismo. Aparte, sin arreglar: la descripción de loteria-sfn-execution-failed-prod sigue diciendo «Because the machine has no Retry/Catch» — y la máquina lleva las dos cosas desde PR-031.1 y PR-033. Es lo primero que se lee en el correo de alerta, así que el texto que debería orientar la respuesta describe una máquina que ya no existe. Anotado en PR-031.2, sin arreglar. Aparte: tener un log group no es llenarlo, y este costó dos intentos — al comprobarlo, describe-log-streams reporta storedBytes 0 con minutos de retraso, hay que leer los eventos y no los metadatos."}},

    {id:"sns", x:890, y:756, w:220, h:72, st:"ok", t:"SNS → correo", s:["loteria-alerts-prod"],
     title:"Las alertas", desc:"Topic con suscripción por correo, confirmada. Avisa de que algo falló y, desde que el gate está en la cadena, también de QUÉ dato estaba mal: el mensaje de NotifyDQFailure lleva la suite, la expectativa y la columna.",
     kv:{"Topic":"loteria-alerts-prod","Suscripción":"correo del owner, confirmada","Quien publica":"7 alarmas + NotifyDQFailure"}},

    {id:"consumer", x:1136, y:756, w:212, h:72, st:"off", t:"Consumidor", s:["no existe","aplazado a propósito"],
     title:"El grifo que falta", desc:"Siete tablas gold se construyen cada jueves y nadie las bebe. No hay ni una línea de QuickSight, dashboard o API en el repo.",
     kv:{"Estado":"aplazado por decisión explícita","Lo más cerca":"el rol de SageMaker, repuntado a silver/ y gold/ el 25 sep","Nota":"el README promete QuickSight desde 2025"},
     warn:{k:"p",t:"Que no haya consumidor es lo que hizo barato arreglar el defecto B: durante cinco semanas las tablas gold estuvieron vacías unos minutos cada jueves y nadie lo notó, porque no había nadie mirando. El día que exista un consumidor, ese mismo defecto habría sido un incidente."}}
  ];

  /* Aristas. k: "" | pend | manual. route elige el trazado en diagram.js. */
  const EDGES = [
    {a:"canary", b:"site", k:"", lab:"miércoles", route:"up",  lx:398, ly:98},
    {a:"extract",b:"site", k:"", lab:"jueves",    route:"up2", lx:640, ly:106},
    {a:"eb", b:"sfn", k:"", lab:""},
    {a:"extract", b:"transform", k:"", lab:""},
    {a:"transform", b:"crawlers", k:"", lab:""},
    {a:"crawlers", b:"dq", k:"", lab:""},
    {a:"dq", b:"gold", k:"", lab:""},
    {a:"extract",  b:"s3p", k:"", lab:"escribe raw/",    route:"write", tx:516, lx:522, ly:370},
    {a:"transform",b:"s3p", k:"", lab:"escribe silver/", route:"write", tx:666, lx:672, ly:388},
    {a:"gold",     b:"s3p", k:"", lab:"CTAS → run=",     route:"write", tx:816, lx:898, ly:360},
    /* El swap: el CTAS escribe al lado y ESTA llamada es la que publica. Va por el
       canal libre de 28 px entre el borde derecho de las cajas y el marco de la cuenta. */
    {a:"gold", b:"cat", k:"", lab:"UpdateTable · publica", route:"promote", tx:660, lx:748, ly:514},
    {a:"obs", b:"sns", k:"", lab:""},
    {a:"ci", b:"owner", k:"manual", lab:"", route:"downleft"},
    {a:"owner", b:"sfn", k:"manual", lab:"artefactos", route:"bridge", lx:214, ly:348}
  ];

  /* Texto suelto sobre el lienzo. */
  const NOTES = [
    {x:426, y:514, t:"Los crawlers registran silver aquí."},
    {x:44,  y:448, t:"Ningún workflow tiene credenciales de AWS.", color:"var(--flow)", weight:700},
    {x:44,  y:466, t:"terraform init -backend=false: no puede leer"},
    {x:44,  y:482, t:"ni siquiera el estado remoto."}
  ];

  /* Las dos líneas de texto dentro del marco de la VPC. */
  const VPC_LABELS = {
    x: 440,
    title: {y: 666, t: "VPC 10.0.0.0/16 · NAT APAGADO · SIN CONSUMIDORES"},
    note:  {y: 688, t: "El extractor no tiene vpc_config y Glue no tiene connection. Su único consumidor sería SageMaker, que está apagado."}
  };

  /* La NO-conexión entre el plano de control y la cuenta: línea tachada. */
  const GAP = {x1:380, x2:398, y:300, label:{x:389, y:258, t:"sin conexión"}};

  /* Chips de prefijo dentro de la caja del bucket particionado. */
  const PREFIXES = [
    {k:"raw/",        v:"119 .txt",         x:436},
    {k:"silver/",     v:"124 447 filas",    x:556},
    {k:"gold/",       v:"13 vivos · 13+13", x:676},
    {k:"quarantine/", v:"vacío, y así debe", x:796},
    {k:"sql/gold/",   v:"los 7 .sql",       x:916}
  ];

  /* Guion de la corrida semanal, paso a paso. */
  const RUN = [
    {id:"eb",    t:"El jueves a las 18:00 UTC, una regla de EventBridge arranca la máquina de estados."},
    {id:"sfn",   t:"Step Functions toma el control y conduce los nueve estados de aquí en adelante."},
    {id:"extract",t:"El Lambda extractor pide el sorteo al sitio a través de scrape.do —desde el 24 de septiembre sin render, a 10 créditos en vez de 25— y sube el .txt crudo a raw/. Si el sorteo ya está en silver/, no hace nada. Si el proxy devuelve un 502, el Retry NO engancha: llega como ValueError y la corrida tiene un solo intento."},
    {id:"s3p",   t:"Bronze: el .txt queda intacto en raw/year=/sorteo=. Nunca se modifica. Hoy son 119 archivos, el último el Ordinario 3138."},
    {id:"transform",t:"El job de Glue parsea el texto, limpia con pandas y escribe Parquet en silver/, cada fila con su run_id —el nombre de esta ejecución—, ingested_at, source_key y parser_version. Las líneas que no entiende ya no desaparecen: se cuentan, y las raras van a quarantine/. Todo eso está desplegado y el 3138 será el primer sorteo que lo atraviese."},
    {id:"crawlers",t:"Dos crawlers registran la partición nueva en el catálogo —con el esquema que declara Terraform, no uno inferido—, y la máquina espera de verdad a que terminen antes de seguir — comprobando el mensaje del último crawl, no un estado READY que también es READY una semana después."},
    {id:"dq",    t:"El gate valida el Silver entero —28 expectativas sobre 119 sorteos y 125 337 premios— antes de tocar Gold. Si una falla, el Catch va a NotifyDQFailure y Gold no se construye. La corrida del 8 de octubre pasó por aquí en 95 s con veredicto PASS, y fue la primera en que las cuatro expectativas de linaje evaluaron filas reales."},
    {id:"athena",t:"Athena ejecuta los siete CTAS, de tres en tres. Cada uno escribe en gold/<tabla>/run=<ejecución>/ y crea una tabla __stg_: al lado de la publicada, sin tocarla. Si un CTAS falla aquí, no ha cambiado nada."},
    {id:"gold",  t:"Solo cuando Athena terminó bien, el Lambda publica: un único UpdateTable mueve el puntero de la tabla, y en las tres tablas particionadas mueve también sus particiones —actualizándolas, nunca borrándolas y recreándolas, porque ese camino pasa por un instante en el que la tabla no tiene ninguna."},
    {id:"cat",   t:"El catálogo queda apuntando a la generación nueva — y desde el 27 de septiembre un cuarto estado, RetireGold, borra las que quedaron atrás salvo una. Corre DESPUÉS del swap y tiene permitido fallar sin tumbar la corrida: cuando llega, las tablas ya están publicadas y correctas."},
    {id:"obs",   t:"Si algo falló, una alarma de CloudWatch publica en SNS y llega un correo. Si lo que falló fue el gate, el correo nombra la suite, la expectativa y la columna. Si lo que falló fue la ejecución entera, el correo todavía dice que la máquina no tiene Retry ni Catch — y lleva las dos desde hace semanas."},
    {id:"consumer",t:"Y aquí se acaba: las siete tablas existen y nadie las consume. El grifo está aplazado a propósito — que no haya nadie bebiendo es justo lo que hizo barato arreglar el defecto B."}
  ];

  /* Nodos que resalta el botón «Resaltar defectos»: los que hoy cargan un defecto
     abierto y anotado, no los que están apagados sin más. */
  const BAD = ["extract", "obs", "s3s"];

  /* Nodos que resalta el botón «Resaltar lo nuevo»: el linaje (PR-045), aplicado el
     4 de octubre. El transformer lo escribe, los crawlers registran la partición con
     el esquema que ahora declara Terraform, el catálogo lo guarda y Athena lo
     responde con dos vistas. */
  const SPOT = ["transform", "crawlers", "cat", "athena"];

  /* Textos fijos del panel lateral cuando no hay nada seleccionado. */
  const IDLE = {
    chip: "seleccioná una pieza",
    title: "Cómo leer esto",
    desc: "Cada caja es algo que existe (o no) en la cuenta. El color dice su estado. Hacé clic en una para ver sus nombres reales, y pasá el mouse para resaltar sus conexiones."
  };

  const STATE_LABEL = {ok:"desplegado", pend:"sin desplegar", bad:"defecto anotado", off:"apagado"};

  global.DIAGRAM_DATA = {ZONES, NODES, EDGES, NOTES, VPC_LABELS, GAP, PREFIXES, RUN, BAD, SPOT, IDLE, STATE_LABEL};
})(window);
