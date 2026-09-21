/* Arquitectura Lotería Santa Lucía — datos del diagrama.
   Todo lo que describe la arquitectura vive aquí; el render y la interacción
   viven en diagram.js. Para actualizar el diagrama, normalmente solo se toca
   este archivo. Se expone como window.DIAGRAM_DATA. */
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
     kv:{"Acceso":"scrape.do con render=true&super=true&geoCode=GT","Costo":"25 créditos por request","Lo tocan":"el canary (mié) y el extractor (jue)"},
     warn:{k:"p",t:"En agosto 2026 el sitio se rediseñó y movió la lista de premios. El selector viejo seguía encontrando 3 filas, así que el extractor habría escrito un archivo sin premios y la corrida habría salido verde. De ahí el canary."}},

    {id:"ci", x:44, y:166, w:312, h:74, st:"ok", t:"ci.yml · 7 jobs", s:["lint · test · tf-validate ×2","checkov · trivy · bandit · build"],
     title:"CI — la prueba de presión", desc:"Corre en cada pull request y en cada push a master. Siete jobs deliberadamente independientes, para que un cambio de Terraform no espere al de Python y viceversa.",
     kv:{"Credenciales AWS":"ninguna","Terraform":"init -backend=false","checkov":"bloqueante, con baseline","trivy":"no bloqueante → pestaña Security","Mergeado":"PR #45"},
     warn:{k:"p",t:"En su primera corrida encontró dos bugs reales que nadie podía reproducir localmente: great-expectations sin pinear (CI instalaba 1.23.0, el resto 1.20.0) y la acción de Trivy apuntando a una versión inexistente, que mataba el job antes de que checkov llegara a correr."}},

    {id:"canary", x:44, y:262, w:312, h:74, st:"ok", t:"scraper-canary.yml", s:["miércoles 18:00 UTC","abre un issue si cambia el HTML"],
     title:"Canary — 24 h de ventaja", desc:"Golpea el sitio real un día antes que el pipeline y comprueba que los selectores siguen encontrando lo que el extractor espera. Si el sitio cambió, abre un issue con el selector que falló.",
     kv:{"Cuándo":"miércoles 18:00 UTC","Por qué el miércoles":"24 h antes del pipeline","Créditos":"el único workflow que los gasta"},
     warn:{k:"p",t:"Estuvo tres semanas en rojo sin avisar: fallaba en el guard del token, cuyo step id no era el que la condición esperaba, así que el paso que abre el issue nunca se disparaba. Un canary que se salta en silencio es peor que no tenerlo."}},

    {id:"owner", x:44, y:356, w:312, h:56, st:"pend", t:"El owner, a mano", s:["make build → aws s3 cp → terraform apply"],
     title:"El puente humano", desc:"La única vía real entre GitHub y la cuenta de AWS. Terraform no gestiona los objetos de código en S3, así que construir y subir los zips es un paso manual.",
     kv:{"Artefactos":"lambda_layer.zip · lambda_package.zip · lottery_transformer.zip","Del gate":"loteria_silver_dq.py · loteria_dq_lib.zip","Destino":"s3://lambda-code-zip-prod","Al día":"20 sep 2026, con el fix de PR-033.2"}},

    {id:"eb", x:424, y:158, w:180, h:56, st:"ok", t:"EventBridge", s:["cron(0 18 ? * THU *)"],
     title:"El disparador semanal", desc:"Una sola regla de cron. Arranca la máquina de estados los jueves a las 18:00 UTC (12:00 en Guatemala).",
     kv:{"Regla":"lottery-etl-weekly-trigger-prod","Cuándo":"jueves 18:00 UTC"},
     warn:{k:"p",t:"Se movió del lunes al jueves: los sorteos del sábado dejan el sitio tras una sala de espera de Cloudflare durante días, y una corrida el lunes caía justo ahí. El jueves es el punto tranquilo de la semana."}},

    {id:"sfn", x:628, y:158, w:236, h:56, st:"ok", t:"Step Functions", s:["lottery-etl-pipeline-prod"],
     title:"El orquestador", desc:"La máquina de estados que conduce todo el pipeline: decide el orden, reintenta, y desde el 16 de septiembre corta el paso a Gold si la calidad falla.",
     kv:{"Nombre":"lottery-etl-pipeline-prod","Estados":"7 · el gate entre los crawlers y Gold","Logging":"ALL, con datos de ejecución","Rol":"sfn-lottery-execution-role-prod","Última corrida":"17 sep 2026 · SUCCEEDED"}},

    {id:"tfstate", x:1140, y:158, w:216, h:56, st:"ok", t:"Estado de Terraform", s:["S3 + lock DynamoDB"],
     title:"Estado remoto", desc:"El estado de Terraform vive en S3 con bloqueo en DynamoDB. El estado legacy se perdió una vez y hubo que reconstruirlo importando 67 recursos a mano.",
     kv:{"Bucket":"loteria-tf-state-913524903233","Lock":"loteria-tf-locks","Versionado":"sí, + prevent_destroy"}},

    {id:"extract", x:424, y:252, w:172, h:84, st:"ok", t:"Extractor", s:["Lambda · python","retry ×2 · idempotente","escribe raw/"],
     title:"La toma de agua", desc:"Lambda que scrapea el sorteo de la semana a través del proxy y sube el .txt crudo. Antes de scrapear comprueba si el sorteo ya existe, así que reintentar es seguro.",
     kv:{"Función":"lottery-extractor-prod","Rol":"lottery-lambda-exec-roleprod","Retry":"2 intentos, solo en errores de red","VPC":"ninguna — corre fuera"}},

    {id:"transform", x:612, y:252, w:172, h:84, st:"ok", t:"Transformer", s:["Glue pythonshell 3.9","1 DPU · .sync","raw → silver"],
     title:"La planta de tratamiento", desc:"Job de Glue que parsea el .txt, separa cabecera y cuerpo, limpia con pandas y escribe Parquet particionado por año y sorteo.",
     kv:{"Job":"lottery-transform-prod","Runtime":"Python Shell 3.9 (el techo)","Capacidad":"1 DPU","Salida":"silver/{sorteos,premios}/"},
     warn:{k:"p",t:"Python Shell solo ofrece 3.6 y 3.9. Ese techo es la razón por la que el gate de calidad tiene que ser un job Spark aparte: Great Expectations 1.x exige Python ≥ 3.10."}},

    {id:"crawlers", x:800, y:252, w:172, h:84, st:"ok", t:"Crawlers ×2", s:["Parallel + polling real","LastCrawl.MessagePrefix","registran silver"],
     title:"El registro en el catálogo", desc:"Dos crawlers en paralelo que registran las particiones nuevas de silver en el catálogo de Glue, para que Athena pueda verlas.",
     kv:{"Crawlers":"lottery-premios-silver-crawler · lottery-sorteos-silver-crawler","Espera":"polling hasta completar"},
     warn:{k:"p",t:"startCrawler no tiene variante .sync: la tarea terminaba en cuanto la API aceptaba la llamada, no cuando el crawl acababa. Los CTAS de gold leían un catálogo viejo y la tabla salía sin el sorteo nuevo, en silencio. PR-026.1 lo arregló con un bucle de polling."}},

    {id:"dq", x:988, y:252, w:172, h:84, st:"ok", t:"Gate de calidad", s:["Glue 5.0 · Spark","20 expectativas","corta el paso a Gold"],
     title:"El laboratorio — ya en la cadena", desc:"Valida el Silver entero contra dos suites de Great Expectations ANTES de tocar Gold. Si una expectativa falla, Gold no se construye: el Catch de la máquina lleva a NotifyDQFailure y la alerta nombra la suite, la expectativa y la columna.",
     kv:{"Estado":"aplicado 16 sep 2026","Cadena":"RunSilverCrawlers → RunSilverDQ → PrepGold","Si falla":"Catch → NotifyDQFailure → SilverDQFailed","Alcance":"20 expectativas · 116 sorteos · 121 945 premios","Runtime":"Glue 5.0 / Python 3.11","Rol":"glue_dq_role — solo lectura","Timeout":"60 min (PR-033.1)"},
     warn:{k:"p",t:"Verificado en los DOS sentidos, que es lo que importa: una corrida validó el Silver real y otra, apuntada a un prefijo inexistente, falló diciendo «esto es un problema de cableado, no de calidad». Un gate que solo ha pasado es indistinguible de no tener gate."}},

    {id:"gold", x:1176, y:252, w:172, h:84, st:"ok", t:"Gold", s:["Map · concurrencia 3","purga λ + CTAS Athena","7 tablas"],
     title:"El embotellado", desc:"Siete consultas CTAS de Athena que construyen las tablas de negocio. Una Lambda de purga borra la tabla y vacía su prefijo antes de cada CTAS, porque Athena se niega a escribir sobre una ubicación no vacía.",
     kv:{"Tablas":"draw_summary · winning_number_frequency · terminations · letters_distribution · geo_winnings · vendor_leaderboard · time_series","Lambda":"lottery-gold-purge-prod","Concurrencia":"3 de 7 a la vez"},
     warn:{k:"b",t:"Defectos 042 y 043 viven aquí: la publicación no es atómica (hay una ventana en que la tabla no existe) y se reconstruye el histórico entero cada semana para añadir un solo sorteo."}},

    {id:"s3p", x:424, y:400, w:620, h:96, st:"ok", t:"S3 · lottery-partitioned-storage-prod", s:[],
     title:"El lago", desc:"El bucket que sostiene las tres capas. Tiene versionado, una política que deniega el borrado a todo el mundo salvo la raíz de la cuenta, y prevent_destroy en Terraform.",
     kv:{"Prefijos":"raw/ · silver/ · gold/ · sql/gold/","Silver":"116 sorteos y 121 945 premios en 232 Parquet","Al día hasta":"sorteo 3136 · 17 sep 2026","Protección":"versionado + Deny + prevent_destroy"}},

    {id:"s3s", x:1064, y:400, w:284, h:96, st:"off", t:"S3 · lottery-data-simple-prod", s:["escrituras detenidas el 20 sep","347 objetos congelados","ni escritor ni lector"],
     title:"El tanque huérfano, ya cerrado por arriba", desc:"El transformer y el extractor escribían aquí una copia plana de cada Parquet y cada .txt. Tenía sentido cuando era la única forma de mirar los datos sin pelear con particiones Hive; hoy Athena lee las tres capas. Desde el 20 sep a las 22:31 UTC las tres escrituras están apagadas por bandera: el bucket sigue existiendo, pero ya no entra ni sale nada de él.",
     kv:{"Defecto":"A → PR-041 (a medio cerrar)","Escrituras":"detenidas el 20 sep 2026 (PR-041.1)","Contenido":"347 objetos · 540 versiones · 9 MB","Lectores":"ninguno activo, pero SageMaker tiene el grant","Borrado":"no antes del 20 oct 2026 (PR-041.3)"},
     warn:{k:"b",t:"Nada de aquí es único: los 115 .txt y los 116 Parquet tienen su contraparte en raw/ y silver/, así que borrarlo no pierde datos. Pero borrarlo no es una línea: la política Deny de PR-002 bloquea el borrado a todo principal salvo la raíz, y con versionado encendido un borrado normal solo deja delete markers. Antes hay que repuntar lottery-sagemaker-s3-read-policy-prod, cuyo único permiso de datos apunta a este bucket. La condición de aborto del 20 oct: si el conteo ya no es 347, algo sigue escribiendo."}},

    {id:"cat", x:424, y:536, w:290, h:72, st:"ok", t:"Glue Data Catalog", s:["lottery_santalucia_db","2 tablas silver + 7 gold"],
     title:"El catálogo", desc:"Las dos tablas silver las registran los crawlers. Las siete gold se registran solas: un CTAS crea la tabla además de escribir el Parquet, así que no necesitan crawler.",
     kv:{"Base":"lottery_santalucia_db","Silver":"por crawler","Gold":"las registra el propio CTAS","Restos":"premios_premios y sorteos_sorteos, de los crawlers legacy de processed/ — nadie las consulta"}},

    {id:"athena", x:730, y:536, w:290, h:72, st:"ok", t:"Athena · lottery-wg", s:["startQueryExecution.sync","ejecuta los 7 CTAS"],
     title:"El motor de consulta", desc:"Workgroup propio. La máquina de estados lanza cada CTAS aquí con la integración .sync, así que espera de verdad a que la consulta termine.",
     kv:{"Workgroup":"lottery-wg","Resultados":"lottery-athena-results-prod"}},

    {id:"lf", x:1036, y:536, w:312, h:72, st:"ok", t:"Lake Formation", s:["gobierna el acceso a las tablas"],
     title:"Permisos del lago", desc:"El acceso al catálogo no vive solo en IAM. Una lectura necesita las dos cosas: el grant de Lake Formation y el permiso lakeformation:GetDataAccess en IAM.",
     kv:{"Modo":"híbrido, con compatibilidad IAM","Ojo":"los grants son aditivos"},
     warn:{k:"p",t:"permissions=[\"ALL\"] nunca converge en el plan, y los grants hechos por consola se mezclan con los de Terraform al leer el estado."}},

    {id:"cw", x:424, y:640, w:0, h:0, st:"ok", t:"", s:[]},

    {id:"obs", x:424, y:756, w:440, h:72, st:"ok", t:"CloudWatch", s:["6 alarmas · dashboard · retención","conteo de objetos por capa"],
     title:"Observabilidad", desc:"Seis alarmas: ejecución fallida, sin éxito reciente, errores del extractor, Glue fallido, crawler que no arrancó y scrape.do fallido. Más un dashboard y una Lambda horaria que publica el número de objetos por capa.",
     kv:{"Alarmas":"6 (la cuenta tiene 10: 4 son de otro proyecto)","Emisor":"lottery-object-count-prod (horaria)","Retención":"sobre los log groups compartidos de Glue","Del gate":"/aws-glue/jobs/loteria-silver-dq-prod"},
     warn:{k:"p",t:"Tener un log group no es llenarlo, y este costó dos intentos: --continuous-log-logGroup transporta el log4j de SPARK y este job nunca arranca Spark, y después el handler que escribía directo se auto-deshabilitó alimentándose con sus propios logs de boto3. Desde el 20 sep 20:55 UTC el grupo lleva las seis líneas del job y el veredicto completo. Ojo al comprobarlo: describe-log-streams reporta storedBytes 0 con minutos de retraso — hay que leer los eventos, no los metadatos."}},

    {id:"sns", x:890, y:756, w:220, h:72, st:"ok", t:"SNS → correo", s:["loteria-alerts-prod"],
     title:"Las alertas", desc:"Topic con suscripción por correo, confirmada. Avisa de que algo falló y, desde que el gate está en la cadena, también de QUÉ dato estaba mal: el mensaje de NotifyDQFailure lleva la suite, la expectativa y la columna.",
     kv:{"Topic":"loteria-alerts-prod","Suscripción":"correo del owner, confirmada","Quien publica":"6 alarmas + NotifyDQFailure"}},

    {id:"consumer", x:1136, y:756, w:212, h:72, st:"off", t:"Consumidor", s:["no existe","aplazado a propósito"],
     title:"El grifo que falta", desc:"Siete tablas gold se construyen cada jueves y nadie las bebe. No hay ni una línea de QuickSight, dashboard o API en el repo.",
     kv:{"Estado":"aplazado por decisión explícita","Nota":"el README promete QuickSight desde 2025"}}
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
    {a:"gold",     b:"s3p", k:"", lab:"escribe gold/",   route:"write", tx:816, lx:906, ly:360},
    {a:"obs", b:"sns", k:"", lab:""},
    {a:"ci", b:"owner", k:"manual", lab:""},
    {a:"owner", b:"sfn", k:"manual", lab:"artefactos", route:"bridge", lx:214, ly:344}
  ];

  /* Texto suelto sobre el lienzo. */
  const NOTES = [
    {x:426, y:524, t:"Los crawlers registran silver aquí · cada CTAS registra su tabla gold por su cuenta, sin crawler."},
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
    {k:"raw/",      v:"year=/sorteo=", x:448},
    {k:"silver/",   v:"122k filas",    x:598},
    {k:"gold/",     v:"7 tablas",      x:748},
    {k:"sql/gold/", v:"los 7 .sql",    x:898}
  ];

  /* Guion de la corrida semanal, paso a paso. */
  const RUN = [
    {id:"eb",    t:"El jueves a las 18:00 UTC, una regla de EventBridge arranca la máquina de estados."},
    {id:"sfn",   t:"Step Functions toma el control y conduce cada paso de aquí en adelante."},
    {id:"extract",t:"El Lambda extractor pide el sorteo al sitio a través de scrape.do y sube el .txt crudo a raw/. Si el sorteo ya existe, no hace nada."},
    {id:"s3p",   t:"Bronze: el .txt queda intacto en raw/year=/sorteo=. Nunca se modifica."},
    {id:"transform",t:"El job de Glue parsea el texto, limpia con pandas y escribe Parquet en silver/. Aquí es donde las filas que no entiende se pierden sin registro (defecto 044)."},
    {id:"crawlers",t:"Dos crawlers registran la partición nueva en el catálogo, y la máquina espera de verdad a que terminen antes de seguir."},
    {id:"dq",    t:"El gate valida el Silver entero —20 expectativas sobre 116 sorteos y 121 945 premios— antes de tocar Gold. Si una falla, el Catch va a NotifyDQFailure y Gold no se construye. La corrida del 17 sep pasó por aquí en 1m56s."},
    {id:"gold",  t:"Siete CTAS reconstruyen las tablas gold. Cada una borra su tabla y vacía su prefijo ANTES de escribir: si falla, se pierde también la copia buena (defecto 042)."},
    {id:"athena",t:"Athena ejecuta cada CTAS y registra la tabla en el catálogo por su cuenta, sin necesitar crawler."},
    {id:"obs",   t:"Si algo falló, una alarma de CloudWatch publica en SNS y llega un correo. Si lo que falló fue el gate, el correo nombra la suite, la expectativa y la columna, y el veredicto entero espera en /aws-glue/jobs/loteria-silver-dq-prod."},
    {id:"consumer",t:"Y aquí se acaba: las siete tablas existen y nadie las consume. El grifo está aplazado a propósito."}
  ];

  /* Nodos que resalta el botón «Resaltar defectos». */
  const BAD = ["s3s", "gold"];

  /* Nodos que resalta el botón «Resaltar lo nuevo»: lo que cambió desde la
     auditoría del 14 sep 2026, que es el gate de calidad y su cadena. */
  const SPOT = ["crawlers", "dq", "gold"];

  /* Textos fijos del panel lateral cuando no hay nada seleccionado. */
  const IDLE = {
    chip: "seleccioná una pieza",
    title: "Cómo leer esto",
    desc: "Cada caja es algo que existe (o no) en la cuenta. El color dice su estado. Hacé clic en una para ver sus nombres reales, y pasá el mouse para resaltar sus conexiones."
  };

  const STATE_LABEL = {ok:"desplegado", pend:"sin desplegar", bad:"defecto anotado", off:"apagado"};

  global.DIAGRAM_DATA = {ZONES, NODES, EDGES, NOTES, VPC_LABELS, GAP, PREFIXES, RUN, BAD, SPOT, IDLE, STATE_LABEL};
})(window);
