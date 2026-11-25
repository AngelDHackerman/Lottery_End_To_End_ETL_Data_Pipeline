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
