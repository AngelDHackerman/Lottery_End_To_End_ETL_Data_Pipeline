/* Extensión Uruguay — datos de los dos diagramas.
   El render vive en diagram-uruguay.js; este archivo solo describe. Se expone como
   window.DIAGRAM_UY = {local, nube}, una entrada por pestaña.

   Lo marcado "funciona hoy" se verificó el 2026-10-04: sondeo de ~60 URLs a 1 req/s,
   dos pilotos (2016-07-01..14 y 2025-09-10..20, 95 peticiones, 0 errores) y el backfill
   completo arrancado ese mismo día. Lo marcado "planificado" es el roadmap
   (roadmap-uruguay.md), no algo que exista. La vista "nube" es una PROPUESTA: las
   decisiones de UY-040 (bucket o prefijo, manifiesto, proxy) siguen abiertas, y cada
   caja que depende de ellas lo dice. */
(function (global) {
  "use strict";

  /* ================================================================
     VISTA 1 — LOCAL (beta): lo que corre en la máquina del owner
     ================================================================ */
  const local = {
    key: "local",
    tab: "Local · beta",
    title: "Extensión Uruguay — en local",
    lede: "Cómo funciona hoy, en la máquina del owner: el scraper baja el crudo a bronce y el manifiesto decide qué ya no hace falta pedir. Lo punteado en ámbar es lo que sigue en el roadmap. Hacé clic en una pieza para ver sus nombres reales.",
    meta: ["rama loteria-uruguaya-test", "solo local", "4 oct 2026"],
    viewBox: "0 0 1400 850",
    play: "▶ Reproducir una corrida del backfill",
    STATE_LABEL: {ok: "funciona hoy", pend: "planificado", bad: "bloqueado a propósito", off: "no se toca aún"},
    legend: [["ok", "Funciona hoy"], ["pend", "Planificado (UY-NNN)"], ["bad", "Bloqueado a propósito"], ["off", "No se toca hasta el merge"]],

    ZONES: [
      {x:24, y:20,  w:1352, h:112, cls:"gh",  label:"INTERNET · DNLQ, MINISTERIO DE ECONOMÍA Y FINANZAS", color:"var(--soft)"},
      {x:24, y:156, w:1352, h:556, cls:"aws", label:"LA MÁQUINA DEL OWNER · WSL · data/uy/ (gitignored)", color:"var(--ink)"},
      {x:24, y:736, w:1352, h:96,  cls:"vpc", label:"GITHUB", color:"var(--off)"}
    ],

    NODES: [
      {id:"site", x:420, y:44, w:330, h:72, st:"ok", t:"www.loteria.gub.uy", s:["nginx · HTML del servidor, sin JS", "sin Cloudflare: 200 en ~0,1 s"],
       title:"La fuente", desc:"El sitio de la Dirección Nacional de Loterías y Quinielas. Renderiza todo en el servidor, responde directo, sin proxy ni sala de espera, y su robots.txt no restringe a nadie. Es lo opuesto a Santa Lucía.",
       kv:{"Página diaria":"ver_resultados.php?vdia=&vmes=&vano=", "Primer dato":"2006-08-11 (por bisección; el selector dice 2007)", "Día sin sorteo":"HTTP 200, ~45,9 KB, sin bloques de juego", "Encoding":"UTF-8 declarado y real", "Desde AWS":"sin probar (UY-005)"},
       warn:{k:"p", t:"Responde 200 incluso cuando no hubo sorteo, así que el código de estado no dice nada: lo decide el contenido. Y el HTML se regenera desde su base con la plantilla de hoy —un extracto de 2007 cita un decreto de 2019—, así que bronce guarda «la página tal como se sirvió el día X», nunca el documento original."}},

      {id:"priv", x:1010, y:44, w:340, h:72, st:"bad", t:"*_DET_INVALIDAS_*.PDF", s:["cédulas de identidad · apuestas anuladas", "nunca se piden"],
       title:"Lo que no se toca", desc:"PDFs que la DNLQ publica junto a cada sorteo desde 2016, con una columna «Cédula Id.». La página de resultados los enlaza; el scraper nunca sigue un enlace por su cuenta y el cliente HTTP rechaza el patrón antes de abrir un socket.",
       kv:{"Patrón":"DET_INVALIDAS (sin distinguir mayúsculas, decodificado)", "Dónde se revisa":"la URL pedida y cada salto de redirección", "Si se intenta":"BlockedURLError, y el log nombra el patrón, no la URL", "Fixtures":"los href se reemplazan; un test escanea la carpeta", "Ley":"18.331 de Uruguay (sin conclusión legal)"},
       warn:{k:"b", t:"Lo único permitido de esa carpeta es RES_INFORMACION_DE_POZOS, y por allowlist, no por «no está bloqueado»: la misma fila de enlaces trae los dos, y una regla más floja tomaría el equivocado el día que el sitio los reordene."}},

      {id:"cli", x:48, y:196, w:220, h:84, st:"ok", t:"backfill CLI", s:["make uy-backfill · uy-pilot", "día por día, reanudable", "--max-requests · --refresh"],
       title:"El que camina el calendario", desc:"python -m loteria_uy.backfill. Recorre el rango día por día: primero la página consolidada, que descubre qué juegos hubo, y solo después los extractos de esos juegos. Se puede cortar en cualquier momento; la siguiente corrida sigue donde quedó.",
       kv:{"Módulo":"src/loteria_uy/backfill.py", "Por defecto":"2006-08-01 → hoy en Montevideo", "Fuentes":"resultados · extractos (+ pdf · pozos)", "Nunca pide":"un día que en Uruguay aún no pasó", "Rango completo":"~7.400 días + un extracto por juego sorteado"}},

      {id:"client", x:420, y:196, w:330, h:84, st:"ok", t:"PoliteClient", s:["1 req/s global · backoff 429/5xx", "User-Agent con contacto (el repo)", "blocklist antes del socket"],
       title:"La única puerta a la red", desc:"Todo lo que sale del paquete pasa por aquí. Un limitador compartido por el proceso entero (dos clientes no duplican el ritmo), reintentos con espera creciente y jitter, Retry-After respetado, y las redirecciones seguidas a mano para poder revisar cada salto.",
       kv:{"Módulo":"src/loteria_uy/http_client.py", "Ritmo":"1 req/s; menos de 1 s se rechaza en el constructor", "Reintenta":"429 · 500 · 502 · 503 · 504 · fallas de transporte", "Contacto":"URL del repo, configurable con LOTERIA_UY_CONTACT", "Caché":"ninguna aquí: es el manifiesto"}},

      {id:"classify", x:420, y:330, w:330, h:84, st:"ok", t:"classify.py", s:["MostrarExtracto('<código>', fecha)", "+ imágenes de cabecera como 2.ª señal", "draw · empty · error"],
       title:"¿Hubo sorteo?", desc:"No es el parser: no saca números. Responde lo que el manifiesto necesita. La señal principal es la tabla de ruteo del propio sitio: cada bloque llama a MostrarExtracto con un código de juego y la fecha. Un código con otra fecha es un error, nunca un sorteo.",
       kv:{"Códigos":"3 vespertina · 4 nocturna · 5 5 de Oro · 2 Kini · 1, 6–26 Lotería", "2.ª señal":"cabezal_quinielas_*, logo_5deoro, logo_kini", "Extracto PHP":"fecha dd/mm/aaaa; la plantilla vacía imprime //", "PDF":"%PDF con 200; 404 = no hay", "Versión":"CLASSIFIER_VERSION 2026-10-04"}},

      {id:"manifest", x:48, y:330, w:220, h:84, st:"ok", t:"manifest.sqlite", s:["la caché: estado por fuente y día", "draw · no_draw · not_yet_published", "missing · error · + fetch_log"],
       title:"La memoria del scraper", desc:"Una fila por (fuente, día) con el estado, el hash del contenido, la URL, Last-Modified y los intentos, más un log de cada petición. Es la caché, no bronce: un día sin sorteo no deja nada en bronce pero sí una fila, y esa fila es la que evita volver a pedirlo.",
       kv:{"Finales":"draw · no_draw · missing (no se vuelven a pedir)", "Se reintentan":"not_yet_published (vacío y de hace < 3 días) · error", "missing":"la página diaria lista el juego y su extracto vino vacío", "Prueba":"segunda pasada del piloto: 0 peticiones, 42 omitidas"}},

      {id:"bronze", x:830, y:304, w:520, h:136, st:"ok", t:"bronce · data/uy/bronze/country=uy/", s:[],
       chips:[{k:"resultados", v:"diaria · 2006→", st:"ok"}, {k:"extractos PHP", v:"por juego · 2006→", st:"ok"}, {k:"PDF firmados", v:"2018-11-30→", st:"ok"}, {k:"pozos 5 de Oro", v:"PDF · 2016→", st:"ok"}],
       title:"Bronce — el crudo, intacto", desc:"Los bytes exactamente como llegaron, solo de sorteos reales. Las rutas copian la futura llave de S3 —source=<fuente>/year=<año>/<fuente>_<fecha>.<ext>—, así que subir a la nube cambia el backend y no las rutas. Cada escritura es atómica: un .tmp y un replace.",
       kv:{"Fuentes por defecto":"resultados + los 3 extractos PHP", "Opcionales":"--sources pdf,pozos (los PDF pesan ~300 KB)", "Piloto":"95 peticiones, 9,3 MB, 0 errores", "Juegos v1":"5 de Oro · Quiniela vespertina · Quiniela nocturna", "Se registran también":"Lotería y Kini, si la página los lista"}},

      {id:"parsers", x:48, y:480, w:220, h:84, st:"pend", t:"Parsers por época", s:["2006–2016-06 · 2016-07→", "extractos HTML y PDF", "UY-022 … UY-024"],
       title:"Del crudo a filas", desc:"Un parser por época de layout y por fuente, configurado por un YAML por juego. Las fronteras de época salen de los datos de bronce, no del brief.",
       kv:{"Montos":"un parser por fuente: 42.501.146,34 vs 35,409,043.86 → Decimal", "Fecha":"la de la URL manda; el encabezado («Setiembre») solo valida", "Ruido":"gif_trasparente · separador · Número del Premio", "Ojo":"«Vacío» ≠ «Sin Aciertos»"}},

      {id:"silver", x:300, y:480, w:260, h:84, st:"pend", t:"Plata local (Parquet)", s:["draws · draw_numbers · prizes", "draw_timing · game_rules", "calendar_events · UY-025"],
       title:"El esquema canónico", desc:"Formato largo para los números (tipo de bolilla, posición y número como texto con ceros), montos en Decimal, reglas con vigencia y los paros y traslados como dimensión con la URL de su resolución.",
       kv:{"Validaciones":"Próximo sorteo · continuidad del n.º de sorteo · Tómbola ⊇ últimas 2 cifras", "Columna":"is_replacement en la Tómbola", "Linaje":"run_id · ingested_at · source_key (patrón de PR-045)", "Horas":"locales + America/Montevideo (hubo horario de verano hasta 2015)"}},

      {id:"dq", x:590, y:480, w:200, h:84, st:"pend", t:"Gate GX", s:["expectativas derivadas", "de los datos reales", "UY-026"],
       title:"El laboratorio", desc:"Suites de Great Expectations para la plata de Uruguay. Se derivan del backfill y no se inventan: es la lección de PR-032, donde las expectativas escritas a priori habrían fallado sobre datos reales.",
       kv:{"Ejemplos":"20 números por Quiniela · 20 distintos en Tómbola", "No es error":"un número repetido en la Quiniela (~17% de los sorteos)", "Rango 5 de Oro":"sin hardcodear hasta confirmarlo (game_rules)"}},

      {id:"gold", x:820, y:480, w:260, h:84, st:"pend", t:"Oro local · DuckDB", s:["chi² por dígito y por posición", "repetidos ~17% · Tómbola ~1,8", "UY-032"],
       title:"La auditoría de aleatoriedad", desc:"Métricas descriptivas, nunca predicción: cada una dice qué esperaba y qué observó. SQL escrito para que corra igual en Athena (Trino) cuando suba a la nube.",
       kv:{"Quiniela":"uniformidad de los 1.000 números, total y por posición", "Tómbola":"reemplazos por sorteo vs ~1,8 esperado", "5 de Oro":"frecuencias dentro de cada versión de reglas", "Pozos":"vacantes, crecimiento, ajuste por inflación (después)"}},

      {id:"report", x:1110, y:480, w:240, h:84, st:"pend", t:"Notebook / reporte", s:["esperado vs observado", "para el portafolio"],
       title:"El que lo lee", desc:"El entregable del análisis local: un notebook o reporte que muestra cada métrica con su expectativa teórica y su intervalo. Es el consumidor que Santa Lucía nunca tuvo."},

      {id:"quar", x:300, y:600, w:260, h:76, st:"pend", t:"quarantine/", s:["filas que el parser rechaza", "contadas y clasificadas (PR-044)"],
       title:"Lo que no se entendió", desc:"El mismo patrón que Santa Lucía: nada se descarta en silencio. Una página que el parser no entiende va aquí con su motivo, y la corrida sigue."},

      {id:"tests", x:820, y:600, w:530, h:76, st:"ok", t:"pytest · 77 tests · loteria_uy al 100%", s:["fixtures reales con los href de privacidad reemplazados", "un escáner falla si un fixture nombra DET_INVALIDAS o «cédula»"],
       title:"La red de seguridad", desc:"77 tests sin red: un cliente falso responde desde páginas reales del 4 de octubre. Cubren la blocklist (mayúsculas, %5F, doble codificación, redirecciones), los reintentos, la clasificación de cada tipo de página y el backfill de punta a punta.",
       kv:{"Suite completa":"565 tests · cobertura total 99,28 % (gate 98)", "Fixtures":"tests/fixtures/uy/ · 8 páginas · README con su origen", "Script":"scripts/uy_redact_fixture.py", "Lint":"ruff check + format en verde"}},

      {id:"branch", x:48, y:770, w:420, h:52, st:"ok", t:"rama loteria-uruguaya-test", s:["PRs feat/UY-NNN → la rama · nunca apilados"],
       title:"El master de la beta", desc:"Todo PR de Uruguay sale de esta rama y vuelve a ella. master se trae hacia aquí con merge (no rebase) cuando cambia algo compartido."},

      {id:"ci", x:500, y:770, w:380, h:52, st:"ok", t:"ci.yml (el mismo de master)", s:["lint · test · gate 98 sobre loteria + loteria_uy"],
       title:"Un solo CI", desc:"El CI corre en cualquier pull_request, así que los PRs hacia la rama beta quedan cubiertos sin tocar ci.yml. El gate de cobertura mide los dos paquetes juntos."},

      {id:"master", x:930, y:770, w:420, h:52, st:"off", t:"master · Lotería Santa Lucía", s:["no se toca hasta UY-050"],
       title:"El proyecto principal", desc:"Durante la beta, ni src/loteria/, ni terraform/, ni roadmap.md. Los scripts de build copian solo src/loteria, así que nada de loteria_uy puede colarse en un artefacto de Santa Lucía ni redesplegarlo."}
    ],

    EDGES: [
      {a:"cli", b:"client", lab:"URL por fuente y día", lx:276, ly:230},
      {a:"client", b:"site", from:"t", to:"b", lab:"GET · 1 req/s", lx:592, ly:150},
      {a:"client", b:"priv", k:"blocked", from:"r", to:"b", ap:[750, 224], via:[[1180, 224]], bp:[1180, 116], xm:[1180, 170], lab:"rechazado antes del socket", lx:860, ly:216},
      {a:"client", b:"classify", from:"b", to:"t", lab:"bytes + cabeceras", lx:592, ly:310},
      {a:"classify", b:"manifest", from:"l", to:"r", lab:"estado", lx:300, ly:364},
      {a:"cli", b:"manifest", from:"b", to:"t", lab:"¿ya es final?", lx:166, ly:310},
      {a:"classify", b:"bronze", lab:"solo sorteos", lx:756, ly:364},
      {a:"bronze", b:"parsers", k:"pend", from:"b", to:"t", ap:[900, 440], via:[[900, 458], [158, 458]], bp:[158, 480]},
      {a:"parsers", b:"silver", k:"pend"},
      {a:"silver", b:"dq", k:"pend"},
      {a:"dq", b:"gold", k:"pend"},
      {a:"gold", b:"report", k:"pend"},
      {a:"parsers", b:"quar", k:"pend", from:"b", to:"l", ap:[158, 564], via:[[158, 638]], bp:[300, 638]},
      {a:"branch", b:"ci"},
      {a:"ci", b:"master", k:"blocked", xm:[905, 796], lab:"merge en UY-050", lx:868, ly:764}
    ],

    NOTES: [
      {x:590, y:628, t:"Lo ámbar es el roadmap:", color:"var(--pending)", weight:700},
      {x:590, y:644, t:"nada de eso existe aún.", color:"var(--pending)", weight:700}
    ],

    RUN: [
      {id:"cli", t:"make uy-backfill arranca en 2006-08-01, unos días antes del primer dato real (11 de agosto de 2006, encontrado por bisección), para que el propio manifiesto registre dónde empieza la historia."},
      {id:"manifest", t:"Antes de cada petición, el manifiesto responde: si ese día y esa fuente ya están en un estado final, no se pide nada. Una segunda pasada sobre el piloto hizo 0 peticiones."},
      {id:"client", t:"El cliente revisa la URL contra la blocklist, espera su turno —un segundo entre peticiones, para todo el proceso— y la pide con un User-Agent que dice quién es y dónde encontrar el proyecto."},
      {id:"site", t:"El sitio contesta en ~0,1 s, sin proxy. Siempre 200, haya habido sorteo o no: por eso el código de estado no decide nada."},
      {id:"priv", t:"La página trae enlaces a los PDF con cédulas. El scraper no sigue enlaces por su cuenta, y si alguien lo intentara el cliente lo rechaza antes de abrir el socket."},
      {id:"classify", t:"El clasificador busca los MostrarExtracto('<código>', fecha) de la página: cada uno es un juego sorteado ese día. Las imágenes de cabecera se cotejan como segunda señal; si no coinciden, queda una advertencia."},
      {id:"bronze", t:"Si hubo sorteo, los bytes van a bronce tal cual, en una ruta que ya tiene la forma de su futura llave de S3. Si no, no se escribe nada."},
      {id:"manifest", t:"El manifiesto guarda el veredicto, el hash y los juegos. Con eso, el backfill pide el extracto de cada juego listado —y solo de esos— y vuelve a empezar con el día siguiente."},
      {id:"parsers", t:"Lo que sigue es el roadmap: parsers por época convierten el crudo en filas…"},
      {id:"silver", t:"…una plata canónica con reglas con vigencia y calendario de paros…"},
      {id:"dq", t:"…un gate de calidad con expectativas sacadas de los datos…"},
      {id:"gold", t:"…y la auditoría de aleatoriedad: cada métrica con su valor esperado al lado."},
      {id:"report", t:"Al final, alguien que lo lee. Cuando esto esté verde en local (gate G3), recién entonces se sube a la nube."}
    ],

    toggles: [
      {label: "Resaltar lo que ya funciona", ids: ["site", "priv", "cli", "client", "classify", "manifest", "bronze", "tests", "branch", "ci"]},
      {label: "Resaltar lo planificado", ids: ["parsers", "silver", "dq", "gold", "report", "quar"]}
    ],

    IDLE: {chip: "seleccioná una pieza", title: "Cómo leer esto",
           desc: "Verde es código que corre hoy y se probó contra el sitio real. Ámbar punteado es el roadmap. Rojo es algo bloqueado a propósito. Pasá el mouse para ver las conexiones."}
  };

  /* ================================================================
     VISTA 2 — NUBE, después del merge (UY-050): la propuesta
     ================================================================ */
  const nube = {
    key: "nube",
    tab: "Nube · tras el merge",
    title: "Santa Lucía + Uruguay — en la nube",
    lede: "La propuesta para después del merge. Los dos países comparten la cuenta, el lago, el catálogo, Athena, los permisos, la observabilidad y el CI, y cada uno tiene su propia tubería, porque la cadencia y la fuente no se parecen en nada. Lo ámbar no existe todavía y lo rojo es un riesgo sin verificar.",
    meta: ["cuenta 913524903233", "us-east-1", "propuesta · UY-040…UY-050"],
    viewBox: "0 0 1400 850",
    play: "▶ Reproducir un miércoles en la nube",
    STATE_LABEL: {ok: "desplegado hoy", pend: "planificado (UY)", bad: "riesgo sin verificar", off: "aplazado"},
    legend: [["ok", "Desplegado hoy (Santa Lucía)"], ["pend", "Nuevo de Uruguay, planificado"], ["bad", "Riesgo sin verificar"], ["off", "Aplazado"]],

    ZONES: [
      {x:24, y:20,  w:1352, h:100, cls:"gh",  label:"INTERNET", color:"var(--soft)"},
      {x:24, y:150, w:1352, h:560, cls:"aws", label:"CUENTA AWS · 913524903233 · us-east-1", color:"var(--ink)"},
      {x:24, y:728, w:664,  h:112, cls:"gh",  label:"GITHUB · LA MÁQUINA DEL OWNER", color:"var(--soft)"},
      {x:712, y:728, w:664, h:112, cls:"vpc", label:"CONSUMO", color:"var(--off)"}
    ],

    NODES: [
      {id:"sl_site", x:140, y:40, w:330, h:64, st:"ok", t:"loteria.org.gt", s:["tras Cloudflare · vía scrape.do (GT)"],
       title:"La fuente de Santa Lucía", desc:"Sin cambios. Un sorteo por semana, detrás de Cloudflare, al que solo se llega con un proxy residencial guatemalteco.",
       kv:{"Acceso":"scrape.do geoCode=GT&super=true", "Cadencia":"semanal"}},

      {id:"uy_site", x:600, y:40, w:330, h:64, st:"bad", t:"www.loteria.gub.uy", s:["directo desde la casa · ¿y desde AWS?"],
       title:"La fuente de Uruguay — sin probar desde AWS", desc:"Desde la máquina del owner responde directo y sin proxy. Desde una IP de AWS nadie lo ha probado, y Santa Lucía enseñó que eso puede cambiar todo el diseño del extractor.",
       kv:{"Verificación":"UY-005 · una petición desde CloudShell us-east-1", "Si bloquea":"probar sa-east-1 antes de pensar en un proxy", "Cadencia":"Quiniela de lunes a sábado (sábado solo nocturna) · 5 de Oro mié y dom"},
       warn:{k:"b", t:"Es la única incógnita capaz de cambiar la forma de la tubería. Por eso UY-005 está en la fase de exploración y no en la de deploy."}},

      /* --- carril Santa Lucía --- */
      {id:"sl_eb", x:48, y:206, w:150, h:60, st:"ok", t:"EventBridge", s:["jueves 18:00 UTC"],
       title:"Disparador de Santa Lucía", desc:"Sin cambios: lottery-etl-weekly-trigger-prod."},
      {id:"sl_sfn", x:220, y:206, w:170, h:60, st:"ok", t:"Step Functions", s:["lottery-etl-pipeline-prod"],
       title:"Orquestador de Santa Lucía", desc:"Sin cambios. Nueve estados, el gate de calidad entre los crawlers y Gold."},
      {id:"sl_ext", x:412, y:206, w:150, h:60, st:"ok", t:"Extractor", s:["Lambda · scrape.do"],
       title:"Extractor de Santa Lucía", desc:"lottery-extractor-prod. Sin cambios por el merge."},
      {id:"sl_tr", x:590, y:206, w:160, h:60, st:"ok", t:"Transformer", s:["Glue pythonshell 3.9"],
       title:"Transformer de Santa Lucía", desc:"lottery-transform-prod. Escribe silver/ y quarantine/."},
      {id:"sl_cr", x:772, y:206, w:150, h:60, st:"ok", t:"Crawlers ×2", s:["registran particiones"],
       title:"Crawlers de Santa Lucía", desc:"Solo registran particiones: el esquema de silver vive en Terraform desde PR-045.2."},
      {id:"sl_dq", x:944, y:206, w:170, h:60, st:"ok", t:"Gate GX", s:["28 expectativas"],
       title:"Gate de Santa Lucía", desc:"Glue 5.0 + Great Expectations. Si falla, Gold no se construye."},
      {id:"sl_gold", x:1136, y:206, w:214, h:60, st:"ok", t:"Gold · 7 tablas", s:["CTAS al lado + swap"],
       title:"Gold de Santa Lucía", desc:"Build beside + swap atómico, verificado en producción el 25 de septiembre."},

      /* --- capa compartida --- */
      {id:"s3", x:48, y:326, w:512, h:110, st:"ok", t:"S3 · lottery-partitioned-storage-prod", s:[],
       chips:[{k:"raw/", v:"SL", st:"ok"}, {k:"silver/", v:"SL", st:"ok"}, {k:"gold/", v:"SL", st:"ok"}, {k:"quarantine/", v:"SL", st:"ok"}, {k:"country=uy/", v:"nuevo", st:"pend"}],
       title:"El lago — compartido", desc:"La propuesta es reutilizar el bucket con un prefijo por país, porque ya tiene versionado, el Deny de borrado y prevent_destroy. La alternativa es un bucket propio. Lo decide UY-040.",
       kv:{"Uruguay escribiría":"country=uy/{bronze,silver,quarantine,gold}/", "Bronce inicial":"se sube desde el disco local (UY-042), no se vuelve a scrapear", "Ojo":"el Deny de PR-002 exime solo a la raíz y al rol de gold-purge"},
       warn:{k:"p", t:"Si se comparte el bucket, la retención de Gold de Uruguay necesita su propio rol exento en el Deny, o no va a poder borrar nada. Exactamente lo que costó PR-042.2."}},

      {id:"cat", x:600, y:326, w:330, h:110, st:"ok", t:"Glue Data Catalog", s:["lottery_santalucia_db · 12 + 2 vistas", "+ lottery_uy_db (nueva)", "esquemas UY en Terraform desde el día 1"],
       title:"El catálogo — dos bases", desc:"Uruguay tiene su propia base. Sus tablas de plata se declaran en Terraform desde el principio, en vez de crawlearse y después importarse: la lección de PR-045.2, que tuvo que importar 118 particiones porque los crawlers no podían evolucionar el esquema.",
       kv:{"Base nueva":"lottery_uy_db (nombre a decidir en UY-010)", "Tablas":"draws · draw_numbers · prizes · draw_timing · game_rules · calendar_events"}},

      {id:"athena", x:954, y:326, w:396, h:110, st:"ok", t:"Athena · lottery-wg", s:["un workgroup, dos bases", "CTAS al lado + swap, igual en ambos", "piso de 10 MiB por consulta"],
       title:"El motor — compartido", desc:"El mismo workgroup y el mismo patrón de publicación atómica. El costo no cambia de escala: Athena cobra un mínimo de 10 MiB por consulta y Uruguay es chico (PR-043.1).",
       kv:{"Uruguay agrega":"las tablas de oro de la auditoría", "SQL":"el mismo que se probó en local con DuckDB (UY-032)"}},

      /* --- carril Uruguay --- */
      {id:"uy_eb", x:48, y:496, w:150, h:60, st:"pend", t:"EventBridge ×3", s:["America/Montevideo"],
       title:"Disparadores de Uruguay", desc:"Tres horarios en hora de Uruguay: Quiniela después de ~15:30 y ~21:30, y el 5 de Oro después de ~22:30 los miércoles y domingos. Más una revisión al día siguiente por feriados y traslados.",
       kv:{"Por qué 3":"la cadencia uruguaya es diaria, la guatemalteca semanal", "Zona":"America/Montevideo (sin horario de verano desde 2015)"}},
      {id:"uy_sfn", x:220, y:496, w:170, h:60, st:"pend", t:"Step Functions", s:["lottery-uy-pipeline"],
       title:"Orquestador de Uruguay", desc:"Una máquina propia. Las lecciones de Santa Lucía vienen incluidas: el Retry cubre el error que de verdad ocurre (PR-047), y el ASL se valida ya renderizado.", kv:{"Roadmap":"UY-043"}},
      {id:"uy_ext", x:412, y:496, w:150, h:60, st:"pend", t:"Extractor UY", s:["Lambda 3.12 · directo"],
       title:"El mismo scraper de hoy, en Lambda", desc:"El código que hoy corre en local: el cliente, el clasificador y el manifiesto. Cambian el backend de bronce (disco → S3) y el del manifiesto. Una corrida incremental son de 1 a 3 peticiones, muy lejos del límite de Lambda.",
       kv:{"Manifiesto":"tabla DynamoDB o Parquet en S3 (UY-040)", "Blocklist":"la misma, con su test", "Runtime":"3.12: el extractor no hereda el techo de 3.9 de Glue"},
       warn:{k:"p", t:"Si UY-005 encuentra que el sitio bloquea IPs de AWS, esta caja cambia: proxy o región. Por eso se prueba primero."}},
      {id:"uy_tr", x:590, y:496, w:160, h:60, st:"pend", t:"Parsers → plata", s:["por época · YAML"],
       title:"Transform de Uruguay", desc:"Los parsers de UY-022…024. Si el runtime es Glue Python Shell, son 3.9 y el guard de ruff de PR-050 tiene que cubrirlos. Si es Lambda, no. Lo decide UY-010.", kv:{"Roadmap":"UY-040 · UY-042"}},
      {id:"uy_part", x:772, y:496, w:150, h:60, st:"pend", t:"Particiones", s:["sin crawler de esquema"],
       title:"Registro de particiones", desc:"Esquema en Terraform y particiones por API o por un crawler que solo registra carpetas. Nunca un crawler que infiere el esquema."},
      {id:"uy_dq", x:944, y:496, w:170, h:60, st:"pend", t:"Gate GX UY", s:["suites de UY-026"],
       title:"Gate de Uruguay", desc:"Las suites que se derivaron en local, ahora antes de cada oro. Si falla, el oro no se publica."},
      {id:"uy_gold", x:1136, y:496, w:214, h:60, st:"pend", t:"Oro UY", s:["aleatoriedad · pozos"],
       title:"Oro de Uruguay", desc:"Las métricas de UY-032 publicadas con el swap atómico de PR-042: TableInput como allowlist y las acciones singulares de partición en IAM.", kv:{"Roadmap":"UY-044"}},

      /* --- operación compartida --- */
      {id:"lf", x:48, y:612, w:300, h:76, st:"ok", t:"Lake Formation + IAM", s:["+ grants para lottery_uy_db", "ALTER en las TABLAS, no en la base"],
       title:"Las dos puertas — compartidas", desc:"Los grants nuevos para la base de Uruguay se escriben con las lecciones del 24 de septiembre: ALTER sobre las tablas (no solo sobre la base), permisos explícitos (nunca ALL) y lakeformation:GetDataAccess en IAM.", kv:{"Roadmap":"UY-041"}},
      {id:"obs", x:372, y:612, w:320, h:76, st:"ok", t:"CloudWatch", s:["9 alarmas de SL + «sorteo UY faltante»", "canary de gub.uy (UY-045)"],
       title:"Observabilidad — compartida", desc:"Una alarma nueva por sorteo esperado que no llegó, a partir del calendario oficial. Cuidado con la trampa conocida: la evaluación tiene un tope de 7 días, y 0 no es lo mismo que «sin dato».", kv:{"Roadmap":"UY-045"}},
      {id:"sns", x:716, y:612, w:200, h:76, st:"ok", t:"SNS → correo", s:["loteria-alerts-prod"],
       title:"Las alertas — compartidas", desc:"El mismo topic. Los mensajes dicen de qué país es la alerta."},
      {id:"tfstate", x:940, y:612, w:200, h:76, st:"ok", t:"Terraform", s:["un estado · módulos", "reutilizados"],
       title:"Un solo estado", desc:"Uruguay entra como módulos nuevos en el mismo stack. Criterio del merge: el plan no toca ningún recurso de Santa Lucía, solo agrega."},
      {id:"code", x:1164, y:612, w:186, h:76, st:"ok", t:"lambda-code-zip-prod", s:["artefactos de", "ambos países"],
       title:"Bucket de código", desc:"make deploy sube los artefactos de los dos. El de Uruguay se construye aparte, así que un cambio en loteria_uy no redespliega a Santa Lucía."},

      /* --- abajo --- */
      {id:"owner", x:48, y:766, w:300, h:56, st:"pend", t:"El owner · make deploy", s:["+ subida única del bronce local"],
       title:"El puente humano", desc:"Igual que hoy: build → apply → upload. La única novedad es una subida de una sola vez: el bronce que el backfill local juntó durante la beta pasa a S3 tal cual, sin volver a pedirle nada al sitio.", kv:{"Roadmap":"UY-042"}},
      {id:"ci", x:372, y:766, w:300, h:56, st:"ok", t:"ci.yml + canaries", s:["un CI · un canary por país"],
       title:"Un CI para los dos", desc:"El mismo ci.yml; el canary de Uruguay se suma al de Santa Lucía."},
      {id:"consumer", x:736, y:766, w:614, h:56, st:"off", t:"Comparativo entre países · QuickSight / API", s:["aplazado: primero que cada país sea confiable por separado"],
       title:"El grifo que todavía falta", desc:"Con dos países aparece por primera vez algo que comparar. Sigue aplazado: primero cada país tiene que ser confiable por separado."}
    ],

    EDGES: [
      {a:"sl_eb", b:"sl_sfn"}, {a:"sl_sfn", b:"sl_ext"}, {a:"sl_ext", b:"sl_tr"},
      {a:"sl_tr", b:"sl_cr"}, {a:"sl_cr", b:"sl_dq"}, {a:"sl_dq", b:"sl_gold"},
      {a:"sl_ext", b:"sl_site", from:"t", to:"b", ap:[470, 206], via:[[470, 136], [305, 136]], bp:[305, 104], lab:"jueves · proxy", lx:330, ly:131},
      {a:"sl_ext", b:"s3", from:"b", to:"t", ap:[487, 266], bp:[487, 326], lab:"raw/", lx:494, ly:300},
      {a:"sl_tr", b:"s3", from:"b", to:"t", ap:[620, 266], via:[[620, 296], [540, 296]], bp:[540, 326], lab:"silver/", lx:626, ly:290},
      {a:"sl_cr", b:"cat", from:"b", to:"t", ap:[847, 266], bp:[847, 326]},
      {a:"sl_gold", b:"athena", from:"b", to:"t", ap:[1243, 266], bp:[1243, 326], lab:"CTAS → swap", lx:1250, ly:300},

      {a:"uy_eb", b:"uy_sfn", k:"pend"}, {a:"uy_sfn", b:"uy_ext", k:"pend"}, {a:"uy_ext", b:"uy_tr", k:"pend"},
      {a:"uy_tr", b:"uy_part", k:"pend"}, {a:"uy_part", b:"uy_dq", k:"pend"}, {a:"uy_dq", b:"uy_gold", k:"pend"},
      {a:"uy_ext", b:"uy_site", k:"pend", from:"t", to:"b", ap:[550, 496], via:[[550, 470], [575, 470], [575, 128], [765, 128]], bp:[765, 104], lab:"3×/día · 1 req/s", lx:590, ly:144},
      {a:"uy_ext", b:"s3", k:"pend", from:"t", to:"b", ap:[487, 496], bp:[487, 436], lab:"country=uy/", lx:400, ly:470},
      {a:"uy_part", b:"cat", k:"pend", from:"t", to:"b", ap:[847, 496], bp:[847, 436]},
      {a:"uy_gold", b:"athena", k:"pend", from:"t", to:"b", ap:[1243, 496], bp:[1243, 436], lab:"CTAS → swap", lx:1250, ly:474},

      {a:"obs", b:"sns"},
      {a:"owner", b:"s3", k:"manual", from:"l", to:"l", ap:[48, 794], via:[[36, 794], [36, 381]], bp:[48, 381], lab:"una vez", lx:52, ly:722}
    ],

    NOTES: [
      {x:48, y:196, t:"SANTA LUCÍA · semanal · desplegado", color:"var(--flow)", weight:700},
      {x:48, y:486, t:"URUGUAY · diario · planificado (UY-040 … UY-045)", color:"var(--pending)", weight:700},
      {x:48, y:318, t:"COMPARTIDO · lago, catálogo, motor", color:"var(--soft)", weight:700},
      {x:48, y:602, t:"COMPARTIDO · permisos, observabilidad, despliegue", color:"var(--soft)", weight:700}
    ],

    RUN: [
      {id:"uy_eb", t:"Un miércoles a las ~15:30 en Montevideo, el primer disparador de Uruguay arranca su máquina. Santa Lucía no se entera: su disparador es el del jueves."},
      {id:"uy_sfn", t:"La máquina de Uruguay conduce su propia cadena, con el Retry escrito para el error que de verdad ocurre."},
      {id:"uy_ext", t:"El extractor consulta el manifiesto y pide solo lo que falta: la página del día y el extracto de la Quiniela vespertina. A 1 req/s, con la misma blocklist que en local."},
      {id:"uy_site", t:"El sitio responde. Si desde AWS no respondiera, el diseño cambia, y por eso UY-005 lo prueba antes de escribir una línea de Terraform."},
      {id:"s3", t:"El crudo cae en country=uy/bronze/ del mismo lago. Los años de historia ya están ahí: subieron una sola vez desde el disco local (UY-042)."},
      {id:"uy_tr", t:"Los parsers por época producen la plata canónica; lo que no entienden va a cuarentena con su motivo."},
      {id:"uy_part", t:"La partición nueva se registra en una tabla cuyo esquema declara Terraform. Ningún crawler adivina columnas."},
      {id:"uy_dq", t:"El gate valida la plata de Uruguay. Si falla, el oro no se toca y el correo dice qué expectativa falló."},
      {id:"athena", t:"Athena construye el oro de Uruguay al lado del publicado, en el mismo workgroup que Santa Lucía…"},
      {id:"uy_gold", t:"…y un swap atómico lo publica. A las ~21:30 se repite con la nocturna, y a las ~22:30 con el 5 de Oro."},
      {id:"cat", t:"El catálogo tiene dos bases, una por país, gobernadas por las mismas dos puertas de permisos."},
      {id:"obs", t:"Si un sorteo esperado no llegó, la alarma nueva lo dice. El jueves, la tubería de Santa Lucía corre igual que siempre: el merge no le cambió nada."}
    ],

    toggles: [
      {label: "Resaltar lo compartido", ids: ["s3", "cat", "athena", "lf", "obs", "sns", "tfstate", "code", "ci"]},
      {label: "Resaltar lo nuevo de Uruguay", ids: ["uy_site", "uy_eb", "uy_sfn", "uy_ext", "uy_tr", "uy_part", "uy_dq", "uy_gold", "owner"]}
    ],

    IDLE: {chip: "seleccioná una pieza", title: "Cómo leer esto",
           desc: "Arriba, la tubería de Santa Lucía tal como está desplegada hoy. Abajo, la de Uruguay. En el medio y al pie, lo que comparten. Hacé clic en una caja para ver qué decide el roadmap sobre ella."}
  };

  global.DIAGRAM_UY = {local, nube};
})(window);
