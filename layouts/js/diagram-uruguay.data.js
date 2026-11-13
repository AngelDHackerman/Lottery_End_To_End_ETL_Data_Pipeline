/* Extensión Uruguay — datos de los dos diagramas.
   El render vive en diagram-uruguay.js; este archivo solo describe. Se expone como
   window.DIAGRAM_UY = {nube, paises}, una entrada por pestaña.

   Reescrito en UY-050.3 (2026-11-13). La versión del 4 de octubre mostraba el scraper
   local y una PROPUESTA de nube; las dos quedaron viejas. Ahora las dos pestañas
   describen lo desplegado:

   - "nube": la corrida nocturna de Uruguay, pieza por pieza.
   - "paises": Santa Lucía y Uruguay lado a lado, con lo que comparten y lo que no.

   Los nombres, tiempos y límites salen de terraform/uy/ (pipeline.tf, fetch.tf,
   silver.tf, dq.tf, gold.tf, alarms.tf, catalog.tf, manifest.tf, ecr.tf). Los conteos
   se leyeron de la cuenta el 2026-11-13, después de la corrida programada del 12 de
   noviembre: filas de plata por Athena (lottery-uy-wg), objetos de uy/raw/ por S3,
   alarmas por CloudWatch, tablas por Glue y la salida de esa ejecución de Step
   Functions. Lo de Santa Lucía se releyó el mismo día: 9 alarmas, 12 tablas y 2
   vistas, y la regla del jueves. */
(function (global) {
  "use strict";

  /* ================================================================
     VISTA 1 — LA CORRIDA NOCTURNA DE URUGUAY, tal como está desplegada
     ================================================================ */
  const nube = {
    key: "nube",
    tab: "Uruguay · la corrida nocturna",
    title: "Extensión Uruguay — la corrida nocturna",
    lede: "Lo que corre cada noche a las 23:30 de Montevideo: una máquina de estados con cuatro pasos que pide al sitio solo lo nuevo, reescribe la plata del año, la valida y publica el oro. Todo lo verde está desplegado. Hacé clic en una pieza para ver sus nombres reales.",
    meta: ["cuenta 913524903233", "us-east-1", "13.021 sorteos · 2006-08-11 → 2026-11-12", "13 nov 2026"],
    viewBox: "0 0 1400 850",
    play: "▶ Reproducir la corrida del 12 de noviembre",
    STATE_LABEL: {ok: "desplegado", pend: "pendiente", bad: "bloqueado a propósito", off: "aplazado"},
    legend: [["ok", "Desplegado y corriendo"], ["bad", "Bloqueado a propósito"]],

    ZONES: [
      {x:24, y:20,  w:1352, h:112, cls:"gh",  label:"INTERNET · DNLQ, MINISTERIO DE ECONOMÍA Y FINANZAS", color:"var(--soft)"},
      {x:24, y:156, w:1352, h:556, cls:"aws", label:"CUENTA AWS · 913524903233 · us-east-1 · stack terraform/uy/", color:"var(--ink)"},
      {x:24, y:736, w:1352, h:96,  cls:"vpc", label:"GITHUB · LA MÁQUINA DEL OWNER", color:"var(--off)"}
    ],

    NODES: [
      {id:"site", x:420, y:44, w:330, h:72, st:"ok", t:"www.loteria.gub.uy", s:["nginx · HTML del servidor, sin JS", "directo, sin proxy: 200 en menos de 1 s"],
       title:"La fuente", desc:"El sitio de la Dirección Nacional de Loterías y Quinielas. Renderiza todo en el servidor y responde directo, sin proxy ni sala de espera, también desde una Lambda en us-east-1. Es lo opuesto a Santa Lucía.",
       kv:{"Página diaria":"ver_resultados.php?vdia=&vmes=&vano=", "Extractos":"una página PHP por juego y un PDF desde el 2018-11-30", "Pozos del 5 de Oro":"un PDF por sorteo desde el 2016-06-01; trae el número de sorteo", "Primer dato":"2006-08-11", "Desde AWS":"8 de 8 peticiones en HTTP 200 desde la Lambda (2026-11-04)"},
       warn:{k:"p", t:"Responde 200 incluso cuando no hubo sorteo, así que el código de estado no dice nada: lo decide el contenido. Y la página diaria lleva incrustada la hora de la consulta, así que sus bytes cambian en cada petición aunque diga lo mismo: lo que se compara es la página ya parseada."}},

      {id:"priv", x:1010, y:44, w:340, h:72, st:"bad", t:"*_DET_INVALIDAS_*.PDF", s:["cédulas de identidad · apuestas anuladas", "nunca se piden"],
       title:"Lo que no se toca", desc:"PDFs que la DNLQ publica junto a cada sorteo desde 2016, con una columna «Cédula Id.». La página de resultados los enlaza; el scraper nunca sigue un enlace por su cuenta y el cliente HTTP rechaza el patrón antes de abrir un socket.",
       kv:{"Patrón":"DET_INVALIDAS (sin distinguir mayúsculas, decodificado)", "Dónde vive":"src/sorteos/uy/privacy.py, en código y nunca en un YAML; el cliente no se puede crear sin blocklist", "Dónde se revisa":"la URL pedida y cada salto de redirección", "Si se intenta":"BlockedURLError, y el log nombra el patrón, no la URL", "Fixtures":"los href se reemplazan; un test escanea la carpeta", "Ley":"N.º 18.331 de Uruguay (sin conclusión legal)"},
       warn:{k:"b", t:"Lo único permitido de esa carpeta es RES_INFORMACION_DE_POZOS, y por allowlist, no por «no está bloqueado»: la misma fila de enlaces trae los dos, y una regla más floja tomaría el equivocado el día que el sitio los reordene."}},

      /* --- la cadena de la noche --- */
      {id:"sched", x:48, y:196, w:176, h:84, st:"ok", t:"EventBridge Scheduler", s:["23:30 America/Montevideo", "todas las noches", "0 reintentos"],
       title:"El disparador", desc:"Un solo horario por día, en hora de Uruguay, después de que cerró el último sorteo (la Nocturna termina hacia las 21:20 y el 5 de Oro hacia las 22:30). No reintenta: si la corrida falla, la de la noche siguiente recoge lo que quedó abierto.",
       kv:{"Nombre":"lottery-uy-nightly-prod", "Expresión":"cron(30 23 * * ? *) · America/Montevideo", "Reintentos":"0", "Primera corrida programada":"2026-11-09"}},

      {id:"sfn", x:272, y:196, w:176, h:84, st:"ok", t:"Step Functions", s:["lottery-uy-pipeline-prod", "4 pasos · tope de 1 hora", "logs ALL"],
       title:"El orquestador", desc:"Fetch → Silver → ValidateSilver → BuildGold. Ningún paso atrapa su propio error: si algo falla, la ejecución termina en FAILED y eso es lo que mira la alarma. Con dry_run la corrida le pregunta al sitio y valida, pero no escribe nada ni construye el oro.",
       kv:{"Estados":"Defaults · CheckInput · Fetch · Silver · ValidateSilver · GoldUnlessDryRun · BuildGold", "Tope":"3.600 s; el peor caso de los cuatro pasos entra", "Reintentos":"errores del servicio Lambda 3 veces; Silver, además, 1 vez ante cualquier error", "Logs":"/aws/vendedlogs/states/lottery-uy-pipeline-prod · 365 días", "Corrida del 12 nov":"SUCCEEDED en 3 min 33 s"}},

      {id:"fetch", x:496, y:196, w:176, h:84, st:"ok", t:"Fetch", s:["Lambda 3.12 · zip", "pide solo lo nuevo", "1 petición por segundo"],
       title:"El que le pregunta al sitio", desc:"Recorre los días desde el último que ya tiene. Antes de cada petición el manifiesto responde si esa página ya quedó firme; si es así, no se pide. Guarda los bytes tal como llegaron y anota en el manifiesto qué mostró cada página.",
       kv:{"Función":"lottery-uy-fetch-prod · 256 MB · 900 s", "Ventana":"los últimos 7 días más toda clave que siga abierta", "Se vuelve a pedir":"la página de resultados de los últimos 3 días, y hasta 14 días si al 5 de Oro le falta el PDF de pozos", "Tope":"400 peticiones por corrida", "Corrida del 12 nov":"10 peticiones, 26 omitidas"},
       warn:{k:"p", t:"Una página de resultados pedida a media tarde ya dice «sorteo» pero solo trae la Vespertina. Por eso las páginas recientes se vuelven a pedir aunque estén en estado final: si no, la Nocturna nunca se descubriría."}},

      {id:"silver", x:720, y:196, w:176, h:84, st:"ok", t:"Silver", s:["Lambda · imagen de ECR", "parsea y compara 2 fuentes", "reescribe el año tocado"],
       title:"Del crudo a filas", desc:"Parsea la página de resultados y el extracto de cada juego, los compara campo por campo y reescribe los Parquet de los años que cambiaron. Un sorteo que no se puede leer va a cuarentena y no a los datos. Al final recalcula los sorteos que faltan.",
       kv:{"Función":"lottery-uy-silver-prod · 2.048 MB · 900 s", "Por qué imagen":"sus dependencias pesan 222 MB; el límite de un zip es 250 MB", "Qué años":"los que Fetch dejó anotados en el ítem PENDING#silver del manifiesto", "Linaje":"cada fila lleva la clave y el hash de la página de la que salió", "Corrida del 12 nov":"2026 = 560 sorteos, 0 en cuarentena, 42 s de construcción"}},

      {id:"dq", x:944, y:196, w:176, h:84, st:"ok", t:"ValidateSilver", s:["Glue 5.0 · 2 × G.1X", "Great Expectations", "6 suites"],
       title:"El gate de calidad", desc:"Baja toda la plata y corre las seis suites. Si una falla, el job falla, el paso falla y el oro no se construye. Las expectativas salieron de los datos reales del backfill, no se inventaron.",
       kv:{"Job":"lottery-uy-silver-dq-prod · tope de 10 min", "GX":"llega como wheels en un zip (uy/dq/); no se instala desde PyPI", "Arranque":"el script empieza entre 46 y 67 s después de pedido el job", "Veredicto":"/aws-glue/jobs/output, un stream por corrida", "Corrida del 12 nov":"SUCCEEDED · 95 s facturados"}},

      {id:"gold", x:1168, y:196, w:176, h:84, st:"ok", t:"BuildGold", s:["Lambda 3.12 · Athena", "6 tablas, todas o ninguna", "swap atómico"],
       title:"El oro", desc:"Construye las seis tablas al lado de las publicadas, cuenta sus filas y solo si las seis tienen datos las cambia todas juntas. Guarda la generación viva y la anterior; lo demás se borra.",
       kv:{"Función":"lottery-uy-gold-prod · 256 MB · 180 s", "Tablas":"digit_frequency · quiniela_repeats · tombola_replacements · 5_de_oro_frequency · pool_dynamics · punctuality", "Dónde":"uy/gold/<tabla>/run=<generación UTC>/", "Corrida del 12 nov":"generación 20261113T023323Z; retiró la 20261111T143255Z"},
       warn:{k:"p", t:"El bucket niega todo borrado salvo a tres identidades. El rol de esta Lambda es una de ellas, y una segunda regla lo limita a uy/gold/. Sin esa excepción el oro nuevo se publica igual, pero el retiro de la generación vieja falla."}},

      /* --- dónde quedan los datos --- */
      {id:"manifest", x:48, y:330, w:300, h:84, st:"ok", t:"DynamoDB · el manifiesto", s:["lottery-uy-manifest-prod", "un estado por fuente y día + el log", "draw · no_draw · missing · error"],
       title:"La memoria del scraper", desc:"Un ítem por (fuente, día) con el estado, el hash, la URL y los intentos, más un ítem por cada petición hecha. Es lo que evita volver a pedir lo que ya quedó firme. Un índice ralo lista solo las claves abiertas.",
       kv:{"Clave":"pk <fuente>#<fecha> · sk STATE o LOG#…", "Finales":"draw · no_draw · missing", "Se reintentan":"not_yet_published · error (3 fallas iguales → missing)", "Protección":"recuperación a un punto en el tiempo, sin borrado de la tabla", "Tamaño":"~43.600 ítems"}},

      {id:"s3", x:400, y:330, w:560, h:110, st:"ok", t:"S3 · lottery-partitioned-storage-prod · uy/", s:[],
       chips:[{k:"uy/raw/", v:"21.295 objetos · 1,06 GB", st:"ok"}, {k:"uy/silver/", v:"7 tablas · Parquet", st:"ok"}, {k:"uy/gold/", v:"6 tablas · viva + 1", st:"ok"}],
       title:"El lago — un prefijo dentro del bucket de datos", desc:"Uruguay vive bajo uy/ en el mismo bucket que Santa Lucía, que ya tenía versionado y la negación de borrado. El prefijo va arriba (uy/raw/ y no raw/uy/) porque el transform de Santa Lucía lista todo raw/ y su contador de objetos vigila raw/, silver/ y gold/.",
       kv:{"Bronce":"los bytes tal como llegaron; las llaves copian las rutas del disco local", "Plata":"particiones country / game / year; el año tocado se reescribe entero", "Sin borrados":"una partición que desaparece se reemplaza por un Parquet vacío", "Además":"uy/dq/ guarda el zip de wheels del job de GX"}},

      {id:"athena", x:1012, y:330, w:338, h:110, st:"ok", t:"Athena · lottery-uy-wg", s:["workgroup propio de Uruguay", "tope de 100 MB leídos por consulta", "CTAS al lado, después el swap"],
       title:"El motor", desc:"Un workgroup solo para Uruguay, con un tope de lectura por consulta. El SQL del oro es el mismo que se prueba en local con DuckDB: seis SELECT que el constructor envuelve en un CTAS.",
       kv:{"Resultados":"lottery-athena-results-prod/uy/", "SQL":"sql/uy/gold/NN_gold_<nombre>.sql", "Prueba local":"make uy-gold-local (DuckDB, menos de 1 s)", "Corrida del 12 nov":"entre 1,8 y 3,6 s por tabla"}},

      {id:"gaps", x:400, y:480, w:270, h:84, st:"ok", t:"draw_gaps", s:["sorteos esperados que no llegaron", "4 filas, las 4 explicadas", "0 abiertas"],
       title:"Lo que debió sortearse y no", desc:"El detector usa el anuncio «Próximo sorteo» de cada extracto y, si no sirve, el calendario de la semana. Un hueco queda explicado cuando un evento del calendario oficial (paro, duelo, traslado) cae dentro de su ventana; si no, queda abierto.",
       kv:{"Regla":"el anuncio vale si cae entre 1 y 14 días después; si no, el calendario", "Acierto histórico":"99,8 % en 5 de Oro y más de 99,9 % en la Quiniela", "Un sorteo adelantado":"no es un hueco y nunca alarma", "Código":"src/sorteos/core/gaps.py"}},

      {id:"quar", x:690, y:480, w:270, h:84, st:"ok", t:"quarantine", s:["lo que el parser no pudo leer", "0 filas en toda la historia"],
       title:"Lo que no se entendió", desc:"Nada se descarta en silencio. Un sorteo con una fuente presente pero ilegible va entero a esta tabla con su motivo. Con cuarentena, la corrida sigue pero no recalcula los huecos, y la alarma avisa.",
       kv:{"Tabla":"silver_quarantine", "Hoy":"0 filas sobre 13.021 sorteos", "Lo dudoso pero legible":"no se aparta: lleva una marca en dq_flags (9 marcas, catálogo cerrado)"}},

      {id:"cat", x:1012, y:480, w:338, h:84, st:"ok", t:"Glue Data Catalog · lottery_uy_db", s:["7 tablas de plata en Terraform", "6 de oro, que crea la Lambda", "particiones por proyección: sin crawler"],
       title:"El catálogo", desc:"Las tablas de plata se declaran en Terraform a partir del esquema del código, y sus particiones se calculan por proyección: no hay crawler que adivine columnas ni que haya que esperar. Las de oro las crea y las cambia la Lambda.",
       kv:{"Plata":"draws · draw_numbers · prizes · quarantine · game_rules · calendar_events · draw_gaps", "Filas hoy":"13.021 sorteos · 460.384 números · 6.252 premios", "Esquema":"terraform/uy/silver_tables.json (make uy-catalog-sync)", "Quién lee el oro":"Lake Formation da una tabla nueva solo a quien la crea; el stack otorga SELECT a los lectores"}},

      /* --- operación --- */
      {id:"obs", x:48, y:600, w:800, h:76, st:"ok", t:"CloudWatch · 5 alarmas", s:["corrida fallida · hueco abierto · filas en cuarentena · errores de fetch · 2 días sin éxito", "las métricas salen de la propia corrida: no hay un canario aparte que le pida nada al sitio"],
       title:"Las noches que no fallan también avisan", desc:"Una corrida puede terminar bien y aun así necesitar a alguien: un sitio que bloquea deja claves en error, un sorteo que no llega deja un hueco abierto. Fetch y Silver imprimen sus conteos como métricas y cuatro alarmas los miran; la quinta mira si la máquina falló.",
       kv:{"Alarmas":"lottery-uy-pipeline-prod-failed · lottery-uy-open-draw-gaps-prod · lottery-uy-silver-quarantine-prod · lottery-uy-fetch-errors-prod · lottery-uy-pipeline-prod-no-success-2d", "Métricas":"espacio Loteria/UY: FetchRequests · FetchErrors · OpenDrawGaps · SilverQuarantineRows", "En un dry run":"no se emite ninguna métrica"},
       warn:{k:"p", t:"Las cuatro alarmas nuevas se desplegaron el 12 de noviembre, después de la corrida de esa noche. Reciben su primer dato con la corrida del 13."}},

      {id:"sns", x:872, y:600, w:200, h:76, st:"ok", t:"SNS → correo", s:["loteria-alerts-prod", "el mismo de Santa Lucía"],
       title:"Las alertas", desc:"El topic es el de Santa Lucía, leído como dato desde el stack de Uruguay. El nombre de cada alarma dice de qué país es."},

      {id:"tf", x:1096, y:600, w:254, h:76, st:"ok", t:"Terraform · terraform/uy/", s:["stack y estado propios", "el plan se niega a destruir"],
       title:"Un stack aparte", desc:"Los recursos de Uruguay viven en su propio stack, con su propio estado en el mismo bucket de estados. Si estuvieran en el stack principal, un make deploy hecho desde master los destruiría mientras la rama de Uruguay no estuviera fusionada.",
       kv:{"Estado":"uy/terraform.tfstate", "Comandos":"make uy-tf-plan → make uy-deploy (aplica el plan guardado)", "Guardas":"el plan falla ante cualquier destroy o replace, y valida la máquina de estados ya renderizada"}},

      /* --- abajo --- */
      {id:"local", x:48, y:770, w:380, h:52, st:"ok", t:"El backfill local · 2006 → 2026", s:["subió una sola vez; el local quedó congelado"],
       title:"De dónde salió la historia", desc:"Los veinte años se bajaron del sitio una sola vez, desde la máquina del owner y a una petición por segundo. Ese bronce y su manifiesto se copiaron a la nube tal cual, sin volver a pedirle nada al sitio. Desde entonces hay un solo manifiesto: el de DynamoDB.",
       kv:{"Bronce":"21.239 archivos subidos y verificados uno por uno (tamaño y MD5)", "Manifiesto":"21.726 estados y 21.803 líneas de log migrados", "Plata":"21 años reconstruidos en la nube; las 7 tablas iguales a las locales", "Hoy":"make uy-incremental se niega a correr sin UY_LOCAL=1"}},

      {id:"ci", x:460, y:770, w:438, h:52, st:"ok", t:"ci.yml · el mismo, con dos jobs de Uruguay", s:["la imagen de plata se construye · el zip de GX se prueba en Python 3.11"],
       title:"Un solo CI", desc:"Corre en todo pull request. Además de lint, tests y los escáneres, dos jobs cuidan lo propio de Uruguay: que la imagen de Silver se construya e importe, y que el zip de wheels del job de GX funcione en el Python de Glue 5.0.",
       kv:{"Cobertura":"el gate de 98 % mide loteria y sorteos juntos", "Además":"la build comprueba que el zip de Fetch no importe nada que no lleve dentro"}},

      {id:"owner", x:930, y:770, w:420, h:52, st:"ok", t:"El owner · make uy-tf-plan → uy-deploy", s:["nada llega a producción sin un plan leído"],
       title:"El puente humano", desc:"Igual que en Santa Lucía: fusionar un PR no despliega nada. Alguien corre el plan, lo lee y aplica ese mismo plan guardado."}
    ],

    EDGES: [
      {a:"sched", b:"sfn"}, {a:"sfn", b:"fetch"}, {a:"fetch", b:"silver"}, {a:"silver", b:"dq"}, {a:"dq", b:"gold"},
      {a:"fetch", b:"site", from:"t", to:"b", ap:[584, 196], bp:[584, 116], lab:"GET · 1 req/s", lx:476, ly:150},
      {a:"fetch", b:"priv", k:"blocked", from:"t", to:"b", ap:[640, 196], via:[[640, 172], [1180, 172]], bp:[1180, 116], xm:[1180, 144], lab:"rechazado antes del socket", lx:840, ly:166},
      {a:"fetch", b:"manifest", from:"b", to:"t", ap:[520, 280], via:[[520, 304], [198, 304]], bp:[198, 330], lab:"¿ya quedó firme?", lx:210, ly:298},
      {a:"fetch", b:"s3", from:"b", to:"t", ap:[620, 280], bp:[620, 330], lab:"uy/raw/", lx:628, ly:312},
      {a:"silver", b:"s3", from:"b", to:"t", ap:[808, 280], bp:[808, 330], lab:"uy/silver/", lx:816, ly:312},
      {a:"s3", b:"dq", from:"t", to:"b", ap:[930, 330], via:[[930, 304], [1032, 304]], bp:[1032, 280], lab:"lee la plata", lx:940, ly:298},
      {a:"gold", b:"athena", from:"b", to:"t", ap:[1256, 280], bp:[1256, 330], lab:"6 CTAS", lx:1264, ly:312},
      {a:"athena", b:"s3", from:"l", to:"r", ap:[1012, 385], bp:[960, 385]},
      {a:"athena", b:"cat", from:"b", to:"t", ap:[1181, 440], bp:[1181, 480], lab:"swap", lx:1189, ly:466},
      {a:"s3", b:"gaps", from:"b", to:"t", ap:[535, 440], bp:[535, 480]},
      {a:"s3", b:"quar", from:"b", to:"t", ap:[825, 440], bp:[825, 480]},
      {a:"gaps", b:"obs", from:"b", to:"t", ap:[535, 564], bp:[535, 600], lab:"OpenDrawGaps", lx:543, ly:588},
      {a:"quar", b:"obs", from:"b", to:"t", ap:[825, 564], bp:[825, 600], lab:"SilverQuarantineRows", lx:690, ly:588},
      {a:"obs", b:"sns"},
      {a:"local", b:"s3", k:"manual", from:"l", to:"l", ap:[48, 796], via:[[36, 796], [36, 458], [374, 458], [374, 385]], bp:[400, 385], lab:"una vez", lx:52, ly:728},
      {a:"owner", b:"tf", k:"manual", from:"t", to:"b", ap:[1223, 770], bp:[1223, 676], lab:"plan → apply", lx:1231, ly:728}
    ],

    NOTES: [
      {x:48, y:322, t:"DÓNDE QUEDA", color:"var(--soft)", weight:700},
      {x:48, y:592, t:"QUIÉN AVISA · CÓMO SE DESPLIEGA", color:"var(--soft)", weight:700},
      {x:48, y:500, t:"ECR · lottery-uy-silver-prod", color:"var(--muted)", weight:700},
      {x:48, y:516, t:"la imagen de Silver; etiquetas inmutables,", color:"var(--muted)"},
      {x:48, y:532, t:"una por hash del código; se guardan 5", color:"var(--muted)"}
    ],

    RUN: [
      {id:"sched", t:"12 de noviembre, 23:30 en Montevideo. El Scheduler arranca la máquina de estados. Los sorteos del día ya cerraron: la Vespertina, la Nocturna y, miércoles y domingos, el 5 de Oro."},
      {id:"sfn", t:"La máquina conduce cuatro pasos. Ninguno atrapa su propio error: si uno falla, la ejecución falla y la alarma lo dice."},
      {id:"fetch", t:"Fetch recorre del 6 al 12 de noviembre. De 36 claves posibles, 26 ya estaban firmes en el manifiesto y no se pidieron."},
      {id:"manifest", t:"El manifiesto es la memoria: qué mostró cada página y cuándo. Una página firme no se vuelve a pedir nunca; una reciente, sí, porque todavía puede crecer."},
      {id:"site", t:"Diez peticiones, una por segundo, con un User-Agent que dice quién es. El sitio responde directo, sin proxy."},
      {id:"priv", t:"La página enlaza PDFs con cédulas. El scraper no sigue enlaces por su cuenta, y el cliente rechaza ese patrón antes de abrir el socket."},
      {id:"s3", t:"Cambiaron cinco claves, las cinco del 12 de noviembre: la página de resultados y los dos extractos de la Quiniela, con sus PDF. Los bytes van a uy/raw/ tal como llegaron."},
      {id:"silver", t:"Silver lee qué años quedaron pendientes —solo 2026— y reescribe ese año: 560 sorteos, ninguno en cuarentena."},
      {id:"gaps", t:"Con la plata nueva recalcula los sorteos que faltan: cuatro huecos en veinte años, los cuatro explicados por el calendario oficial. Ninguno abierto."},
      {id:"dq", t:"El job de Glue corre las seis suites de Great Expectations sobre toda la plata. Pasan: 95 segundos facturados."},
      {id:"gold", t:"BuildGold construye las seis tablas al lado de las publicadas y cuenta sus filas."},
      {id:"athena", t:"Athena tarda entre 1,8 y 3,6 segundos por tabla. Las seis tienen datos…"},
      {id:"cat", t:"…así que el catálogo cambia las seis juntas a la generación nueva. Se retira la más vieja; quedan la viva y la anterior."},
      {id:"obs", t:"3 minutos y 33 segundos después, SUCCEEDED. Ninguna alarma se movió. A la noche siguiente, lo mismo."}
    ],

    toggles: [
      {label: "Resaltar la corrida nocturna", ids: ["site", "sched", "sfn", "fetch", "silver", "dq", "gold"]},
      {label: "Resaltar dónde quedan los datos", ids: ["manifest", "s3", "athena", "cat", "gaps", "quar"]}
    ],

    IDLE: {chip: "seleccioná una pieza", title: "Cómo leer esto",
           desc: "Arriba, el sitio. En la primera fila, los pasos de cada noche, de izquierda a derecha. Debajo, dónde queda cada cosa, y al pie quién avisa y cómo se despliega. Verde es lo desplegado; rojo, lo bloqueado a propósito. Pasá el mouse para ver las conexiones."}
  };

  /* ================================================================
     VISTA 2 — LOS DOS PAÍSES: qué comparten y qué no
     ================================================================ */
  const paises = {
    key: "paises",
    tab: "Los dos países",
    title: "Santa Lucía + Uruguay — qué comparten y qué no",
    lede: "Dos tuberías en la misma cuenta. Comparten el bucket de datos, el catálogo, los permisos, el topic de alertas y el CI. No comparten ni el código, ni el horario, ni el stack de Terraform, ni el workgroup de Athena: la fuente y la cadencia no se parecen en nada.",
    meta: ["cuenta 913524903233", "us-east-1", "las dos desplegadas", "13 nov 2026"],
    viewBox: "0 0 1400 850",
    play: "▶ Reproducir una semana",
    STATE_LABEL: {ok: "desplegado", pend: "pendiente", bad: "bloqueado a propósito", off: "aplazado"},
    legend: [["ok", "Desplegado"], ["off", "Aplazado"]],

    ZONES: [
      {x:24, y:20,  w:1352, h:100, cls:"gh",  label:"INTERNET", color:"var(--soft)"},
      {x:24, y:150, w:1352, h:560, cls:"aws", label:"CUENTA AWS · 913524903233 · us-east-1", color:"var(--ink)"},
      {x:24, y:728, w:664,  h:112, cls:"gh",  label:"GITHUB · LA MÁQUINA DEL OWNER", color:"var(--soft)"},
      {x:712, y:728, w:664, h:112, cls:"vpc", label:"CONSUMO", color:"var(--off)"}
    ],

    NODES: [
      {id:"sl_site", x:140, y:40, w:330, h:64, st:"ok", t:"loteria.org.gt", s:["tras Cloudflare · vía un proxy (GT)"],
       title:"La fuente de Santa Lucía", desc:"Un sorteo por semana, detrás de Cloudflare, al que solo se llega con un proxy residencial guatemalteco. Solo muestra el último sorteo: lo que no se bajó a tiempo, se perdió.",
       kv:{"Acceso":"scrape.do con salida en Guatemala", "Cadencia":"semanal", "Historia":"crece desde el primer scrape"}},

      {id:"uy_site", x:600, y:40, w:330, h:64, st:"ok", t:"www.loteria.gub.uy", s:["directo, sin proxy · 1 petición por segundo"],
       title:"La fuente de Uruguay", desc:"Responde directo, también desde AWS, y guarda cada día desde 2006. Por eso Uruguay tuvo un backfill de veinte años y Santa Lucía no.",
       kv:{"Acceso":"directo; 8 de 8 en HTTP 200 desde la Lambda", "Cadencia":"Quiniela de lunes a sábado (el sábado, solo Nocturna) · 5 de Oro miércoles y domingo", "Historia":"desde el 2006-08-11"}},

      /* --- carril Santa Lucía --- */
      {id:"sl_eb", x:48, y:206, w:150, h:60, st:"ok", t:"EventBridge", s:["jueves 18:00 UTC"],
       title:"Disparador de Santa Lucía", desc:"lottery-etl-weekly-trigger-prod, una regla semanal: cron(0 18 ? * THU *)."},
      {id:"sl_sfn", x:220, y:206, w:170, h:60, st:"ok", t:"Step Functions", s:["lottery-etl-pipeline-prod"],
       title:"Orquestador de Santa Lucía", desc:"Su propia máquina de estados, con el gate de calidad entre los crawlers y Gold."},
      {id:"sl_ext", x:412, y:206, w:150, h:60, st:"ok", t:"Extractor", s:["Lambda · proxy"],
       title:"Extractor de Santa Lucía", desc:"lottery-extractor-prod. Código en src/loteria/."},
      {id:"sl_tr", x:590, y:206, w:160, h:60, st:"ok", t:"Transformer", s:["Glue pythonshell 3.9"],
       title:"Transformer de Santa Lucía", desc:"lottery-transform-prod. Escribe silver/ y quarantine/."},
      {id:"sl_cr", x:772, y:206, w:150, h:60, st:"ok", t:"Crawlers ×2", s:["registran particiones"],
       title:"Crawlers de Santa Lucía", desc:"Solo registran particiones: el esquema de silver vive en Terraform. Uruguay no tiene crawlers: sus particiones se calculan por proyección."},
      {id:"sl_dq", x:944, y:206, w:170, h:60, st:"ok", t:"Gate GX", s:["29 expectativas"],
       title:"Gate de Santa Lucía", desc:"Glue 5.0 + Great Expectations. Si falla, Gold no se construye."},
      {id:"sl_gold", x:1136, y:206, w:214, h:60, st:"ok", t:"Gold · 7 tablas", s:["CTAS al lado + swap"],
       title:"Gold de Santa Lucía", desc:"Construye al lado y hace un swap atómico. Es el patrón que el oro de Uruguay copió."},

      /* --- capa compartida --- */
      {id:"s3", x:48, y:326, w:512, h:110, st:"ok", t:"S3 · lottery-partitioned-storage-prod", s:[],
       chips:[{k:"raw/", v:"SL", st:"ok"}, {k:"silver/", v:"SL", st:"ok"}, {k:"gold/", v:"SL", st:"ok"}, {k:"quarantine/", v:"SL", st:"ok"}, {k:"uy/", v:"UY", st:"ok"}],
       title:"El lago — compartido", desc:"Un solo bucket de datos; las capas son prefijos. Uruguay entra con un prefijo arriba de todo, uy/, para que nada de Santa Lucía lo liste ni lo cuente por accidente.",
       kv:{"Uruguay escribe":"uy/raw/ · uy/silver/ · uy/gold/ · uy/dq/", "Protección común":"versionado y una negación de borrado para todos", "Quién puede borrar":"la raíz, el rol de purga de Gold de Santa Lucía y el rol del oro de Uruguay (este, solo bajo uy/gold/)"}},

      {id:"cat", x:600, y:326, w:330, h:110, st:"ok", t:"Glue Data Catalog", s:["lottery_santalucia_db · 12 tablas + 2 vistas", "lottery_uy_db · 7 de plata + 6 de oro", "una base por país"],
       title:"El catálogo — compartido, dos bases", desc:"El mismo catálogo y las mismas reglas, con una base por país. Los permisos de Santa Lucía son comodines sobre sus tablas, así que una base aparte no los toca.",
       kv:{"Santa Lucía":"esquema en Terraform, particiones por crawler", "Uruguay":"esquema en Terraform, particiones por proyección"}},

      {id:"athena", x:954, y:326, w:396, h:110, st:"ok", t:"Athena · dos workgroups", s:["lottery-wg · Santa Lucía", "lottery-uy-wg · Uruguay, tope de 100 MB", "el mismo patrón: CTAS al lado + swap"],
       title:"El motor — mismo servicio, workgroups aparte", desc:"Cada país tiene su workgroup. El de Uruguay vive en su stack y lleva un tope de lectura por consulta. El costo no cambia de escala: Athena cobra un mínimo de 10 MiB por consulta y las dos historias son chicas.",
       kv:{"Resultados":"el mismo bucket de resultados; Uruguay bajo uy/"}},

      /* --- carril Uruguay --- */
      {id:"uy_eb", x:48, y:496, w:150, h:60, st:"ok", t:"Scheduler", s:["23:30 Montevideo"],
       title:"Disparador de Uruguay", desc:"lottery-uy-nightly-prod, todas las noches en hora de Uruguay. Un solo horario basta: a las 23:30 ya cerraron todos los sorteos del día.",
       kv:{"Por qué no es semanal":"allá se sortea casi todos los días"}},
      {id:"uy_sfn", x:220, y:496, w:170, h:60, st:"ok", t:"Step Functions", s:["lottery-uy-pipeline-prod"],
       title:"Orquestador de Uruguay", desc:"Una máquina propia de cuatro pasos. El detalle está en la otra pestaña."},
      {id:"uy_ext", x:412, y:496, w:150, h:60, st:"ok", t:"Fetch", s:["Lambda 3.12 · directo"],
       title:"El scraper de Uruguay", desc:"lottery-uy-fetch-prod. Código en src/sorteos/. Su memoria es una tabla de DynamoDB, no el bucket."},
      {id:"uy_tr", x:590, y:496, w:332, h:60, st:"ok", t:"Silver", s:["Lambda · imagen de ECR · sin crawler"],
       title:"La plata de Uruguay", desc:"lottery-uy-silver-prod. Parsea, compara dos fuentes y reescribe el año tocado. No hay crawler después: las particiones se calculan por proyección."},
      {id:"uy_dq", x:944, y:496, w:170, h:60, st:"ok", t:"Gate GX", s:["6 suites"],
       title:"Gate de Uruguay", desc:"lottery-uy-silver-dq-prod, Glue 5.0. Si falla, el oro no se construye."},
      {id:"uy_gold", x:1136, y:496, w:214, h:60, st:"ok", t:"Oro · 6 tablas", s:["todas o ninguna + swap"],
       title:"Oro de Uruguay", desc:"lottery-uy-gold-prod. Una sola Lambda construye las seis tablas y las cambia juntas."},

      /* --- operación --- */
      {id:"lf", x:48, y:612, w:300, h:76, st:"ok", t:"Lake Formation + IAM", s:["las mismas dos puertas", "permisos por base y por rol"],
       title:"Los permisos — compartidos", desc:"Leer una tabla exige las dos cosas en los dos países: el permiso de Lake Formation y el de IAM. Cada tubería tiene sus propios roles; ninguno de Uruguay puede escribir fuera de uy/."},
      {id:"obs", x:372, y:612, w:320, h:76, st:"ok", t:"CloudWatch", s:["9 alarmas de Santa Lucía", "5 alarmas de Uruguay"],
       title:"Observabilidad — mismo servicio, alarmas propias", desc:"Cada país declara sus alarmas en su stack. Las de Uruguay se llaman lottery-uy-…; las de Santa Lucía, loteria-…"},
      {id:"sns", x:716, y:612, w:200, h:76, st:"ok", t:"SNS → correo", s:["loteria-alerts-prod"],
       title:"Las alertas — compartidas", desc:"Un solo topic y un solo correo. El nombre de la alarma dice de qué país es."},
      {id:"tfstate", x:940, y:612, w:200, h:76, st:"ok", t:"Terraform", s:["dos stacks, dos estados", "terraform/ · terraform/uy/"],
       title:"Dos stacks", desc:"Los estados viven en el mismo bucket con llaves distintas. Un make deploy de Santa Lucía no ve los recursos de Uruguay, y al revés.",
       kv:{"Estados":"main/terraform.tfstate · uy/terraform.tfstate"}},
      {id:"only", x:1164, y:612, w:186, h:76, st:"ok", t:"Solo Uruguay", s:["DynamoDB · el manifiesto", "ECR · la imagen de Silver"],
       title:"Lo que Santa Lucía no tiene", desc:"Una tabla de DynamoDB que recuerda qué mostró cada página, y un repositorio de ECR para la imagen de Silver, cuyas dependencias no entran en un zip."},

      /* --- abajo --- */
      {id:"owner", x:48, y:766, w:300, h:56, st:"ok", t:"El owner", s:["make deploy · make uy-deploy"],
       title:"El puente humano", desc:"Un comando por stack. En los dos, fusionar un PR no despliega nada: alguien lee el plan y lo aplica."},
      {id:"ci", x:372, y:766, w:300, h:56, st:"ok", t:"ci.yml", s:["un CI para los dos"],
       title:"Un CI para los dos", desc:"El mismo workflow. El gate de cobertura mide los dos paquetes juntos, y dos jobs cuidan los artefactos de Uruguay."},
      {id:"consumer", x:736, y:766, w:614, h:56, st:"off", t:"Comparativo entre países · QuickSight / API", s:["aplazado: primero que cada país sea confiable por separado"],
       title:"El grifo que todavía falta", desc:"Con dos países aparece por primera vez algo que comparar. Sigue aplazado."}
    ],

    EDGES: [
      {a:"sl_eb", b:"sl_sfn"}, {a:"sl_sfn", b:"sl_ext"}, {a:"sl_ext", b:"sl_tr"},
      {a:"sl_tr", b:"sl_cr"}, {a:"sl_cr", b:"sl_dq"}, {a:"sl_dq", b:"sl_gold"},
      {a:"sl_ext", b:"sl_site", from:"t", to:"b", ap:[470, 206], via:[[470, 136], [305, 136]], bp:[305, 104], lab:"jueves · proxy", lx:330, ly:131},
      {a:"sl_ext", b:"s3", from:"b", to:"t", ap:[487, 266], bp:[487, 326], lab:"raw/", lx:494, ly:300},
      {a:"sl_tr", b:"s3", from:"b", to:"t", ap:[620, 266], via:[[620, 296], [540, 296]], bp:[540, 326], lab:"silver/", lx:626, ly:290},
      {a:"sl_cr", b:"cat", from:"b", to:"t", ap:[847, 266], bp:[847, 326]},
      {a:"sl_gold", b:"athena", from:"b", to:"t", ap:[1243, 266], bp:[1243, 326], lab:"CTAS → swap", lx:1250, ly:300},

      {a:"uy_eb", b:"uy_sfn"}, {a:"uy_sfn", b:"uy_ext"}, {a:"uy_ext", b:"uy_tr"},
      {a:"uy_tr", b:"uy_dq"}, {a:"uy_dq", b:"uy_gold"},
      {a:"uy_ext", b:"uy_site", from:"t", to:"b", ap:[550, 496], via:[[550, 470], [575, 470], [575, 128], [765, 128]], bp:[765, 104], lab:"cada noche · 1 req/s", lx:590, ly:144},
      {a:"uy_ext", b:"s3", from:"t", to:"b", ap:[487, 496], bp:[487, 436], lab:"uy/raw/", lx:424, ly:470},
      {a:"uy_tr", b:"s3", from:"t", to:"b", ap:[620, 496], via:[[620, 466], [540, 466]], bp:[540, 436], lab:"uy/silver/", lx:626, ly:482},
      {a:"uy_gold", b:"athena", from:"t", to:"b", ap:[1243, 496], bp:[1243, 436], lab:"CTAS → swap", lx:1250, ly:474},

      {a:"obs", b:"sns"}
    ],

    NOTES: [
      {x:48, y:196, t:"SANTA LUCÍA · semanal · src/loteria · terraform/", color:"var(--flow)", weight:700},
      {x:48, y:486, t:"URUGUAY · cada noche · src/sorteos · terraform/uy/", color:"var(--flow)", weight:700},
      {x:48, y:318, t:"COMPARTIDO · lago y catálogo", color:"var(--soft)", weight:700},
      {x:48, y:602, t:"OPERACIÓN · qué es común y qué es de cada uno", color:"var(--soft)", weight:700}
    ],

    RUN: [
      {id:"uy_eb", t:"Cualquier noche a las 23:30 de Montevideo arranca la tubería de Uruguay. Santa Lucía no se entera."},
      {id:"uy_ext", t:"Fetch le pide al sitio uruguayo solo lo nuevo, directo y a una petición por segundo."},
      {id:"s3", t:"El crudo cae bajo uy/ en el mismo bucket donde vive Santa Lucía, cada uno en sus prefijos."},
      {id:"uy_tr", t:"Silver reescribe el año tocado. No hay crawler que esperar."},
      {id:"uy_dq", t:"El gate de Uruguay valida su plata…"},
      {id:"uy_gold", t:"…y su oro se publica con el mismo patrón que el de Santa Lucía: construir al lado y cambiar de una vez."},
      {id:"cat", t:"El catálogo tiene dos bases, una por país, detrás de las mismas dos puertas de permisos."},
      {id:"sl_eb", t:"El jueves a las 18:00 UTC corre la de Santa Lucía, igual que siempre."},
      {id:"sl_ext", t:"Su extractor sale por un proxy, porque su sitio está detrás de Cloudflare."},
      {id:"sl_gold", t:"Su Gold se reconstruye en su workgroup. Ninguna de las dos tuberías depende de la otra."},
      {id:"sns", t:"Si algo falla en cualquiera de las dos, el aviso llega al mismo correo, y el nombre de la alarma dice de qué país es."}
    ],

    toggles: [
      {label: "Resaltar lo compartido", ids: ["s3", "cat", "lf", "sns", "ci"]},
      {label: "Resaltar lo de Uruguay", ids: ["uy_site", "uy_eb", "uy_sfn", "uy_ext", "uy_tr", "uy_dq", "uy_gold", "only"]}
    ],

    IDLE: {chip: "seleccioná una pieza", title: "Cómo leer esto",
           desc: "Arriba, la tubería de Santa Lucía. Abajo, la de Uruguay. En el medio, lo que comparten, y al pie de la cuenta, la operación. Hacé clic en una caja para ver qué es común y qué es de cada país."}
  };

  global.DIAGRAM_UY = {nube, paises};
})(window);
