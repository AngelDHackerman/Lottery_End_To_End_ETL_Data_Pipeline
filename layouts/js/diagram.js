/* Arquitectura Lotería Santa Lucía — render e interacción.
   Los datos (nodos, aristas, textos) viven en diagram.data.js, que debe
   cargarse antes que este archivo. */
(function (D) {
  "use strict";

  if (!D) { throw new Error("diagram.data.js no se cargó antes que diagram.js"); }

  const SVG = "http://www.w3.org/2000/svg";
  const map = document.getElementById("map");

  /* Los de w:0 son marcadores de posición sin caja: no se dibujan. */
  const NODES = D.NODES.filter(n => n.w > 0);
  const byId = {};
  NODES.forEach(n => { byId[n.id] = n; });

  const cx = n => n.x + n.w / 2;
  const cy = n => n.y + n.h / 2;

  function el(tag, attrs, parent) {
    const e = document.createElementNS(SVG, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }

  function text(attrs, content, parent) {
    const t = el("text", attrs, parent);
    t.textContent = content;
    return t;
  }

  /* ============================ RENDER ============================ */

  function drawDefs() {
    const defs = el("defs", {}, map);
    [["mk-flow", "var(--flow)"], ["mk-pend", "var(--pending)"], ["mk-man", "var(--muted)"]]
      .forEach(([id, c]) => {
        const m = el("marker", {id, viewBox:"0 0 10 10", refX:"9", refY:"5", markerWidth:"7",
                                markerHeight:"7", orient:"auto-start-reverse"}, defs);
        el("path", {d:"M0 0 L10 5 L0 10 z", fill:c}, m);
      });
  }

  function drawZones() {
    D.ZONES.forEach(z => {
      el("rect", {x:z.x, y:z.y, width:z.w, height:z.h, rx:4, class:"zone " + z.cls}, map);
      if (z.label) text({x:z.x + 16, y:z.y + 22, class:"ztext", fill:z.color}, z.label, map);
    });

    const v = D.VPC_LABELS;
    text({x:v.x, y:v.title.y, class:"ztext", fill:"var(--off)"}, v.title.t, map);
    text({x:v.x, y:v.note.y, "font-family":"var(--mono)", "font-size":"10.5",
          fill:"var(--muted)"}, v.note.t, map);
  }

  function note(x, y, txt, color, weight) {
    const t = text({x, y, "font-family":"var(--mono)", "font-size":"10",
                    fill: color || "var(--muted)"}, txt, map);
    if (weight) t.setAttribute("font-weight", weight);
    return t;
  }

  function drawNotes() {
    D.NOTES.forEach(n => note(n.x, n.y, n.t, n.color, n.weight));
  }

  /* La cruz roja: GitHub Actions no toca la cuenta de AWS. */
  function drawGap() {
    const g = D.GAP, x1 = g.x1, x2 = g.x2, y = g.y, mid = (x1 + x2) / 2;
    el("line", {x1, y1:y, x2, y2:y, stroke:"var(--breach)", "stroke-width":2.5,
                "stroke-dasharray":"5 4"}, map);
    el("line", {x1:x1 + 2, y1:y - 9, x2:x2 - 2, y2:y + 9, stroke:"var(--breach)",
                "stroke-width":3, "stroke-linecap":"round"}, map);
    el("line", {x1:x2 - 2, y1:y - 9, x2:x1 + 2, y2:y + 9, stroke:"var(--breach)",
                "stroke-width":3, "stroke-linecap":"round"}, map);
    /* El rótulo va GIRADO: el canal entre las dos zonas mide 24 px de ancho y
       cualquier texto horizontal se derrama sobre ambos marcos. De pie cabe. */
    const l = g.label;
    const t = note(l.x, l.y, l.t, "var(--breach)", 700);
    t.setAttribute("text-anchor", "middle");
    t.setAttribute("transform", `rotate(-90 ${l.x} ${l.y})`);
  }

  function drawPrefixChips() {
    D.PREFIXES.forEach(p => {
      el("rect", {x:p.x, y:440, width:136, height:44, rx:2, fill:"var(--surface2)",
                  stroke:"var(--flow)", "stroke-width":1.2}, map);
      text({x:p.x + 68, y:459, "text-anchor":"middle", "font-family":"var(--mono)",
            "font-size":"11", "font-weight":"700", fill:"var(--flow)"}, p.k, map);
      text({x:p.x + 68, y:475, "text-anchor":"middle", "font-family":"var(--mono)",
            "font-size":"9", fill:"var(--muted)"}, p.v, map);
    });
  }

  /* Cada ruta esquiva las cajas que tiene en medio: 386 y 412 son los dos carriles
     verticales del hueco entre zonas, y 232 el carril horizontal entre la fila del
     disparador y la del pipeline. */
  function pathFor(e) {
    const A = byId[e.a], B = byId[e.b];
    if (e.route === "up")
      return `M ${A.x + A.w} ${cy(A)} L 386 ${cy(A)} L 386 104 L ${B.x + 40} 104 L ${B.x + 40} ${B.y + B.h}`;
    if (e.route === "up2")
      return `M ${A.x} ${cy(A)} L 412 ${cy(A)} L 412 112 L ${B.x + B.w - 40} 112 L ${B.x + B.w - 40} ${B.y + B.h}`;
    if (e.route === "write")
      return `M ${cx(A)} ${A.y + A.h} L ${cx(A)} 376 L ${e.tx} 376 L ${e.tx} ${B.y}`;
    if (e.route === "bridge")
      return `M ${A.x + A.w} ${cy(A)} L 386 ${cy(A)} L 386 232 L ${cx(B)} 232 L ${cx(B)} ${B.y + B.h}`;
    return `M ${A.x + A.w} ${cy(A)} L ${B.x} ${cy(B)}`;
  }

  function drawEdges() {
    const layer = el("g", {}, map);
    return D.EDGES.map(e => {
      const cls = "edge" + (e.k ? " " + e.k : "");
      const mk = e.k === "pend" ? "mk-pend" : e.k === "manual" ? "mk-man" : "mk-flow";
      const p = el("path", {d:pathFor(e), class:cls, "marker-end":`url(#${mk})`}, layer);
      p.dataset.a = e.a;
      p.dataset.b = e.b;
      if (e.lab) {
        const A = byId[e.a], B = byId[e.b];
        const lx = e.lx !== undefined ? e.lx : (A.x + A.w + B.x) / 2;
        const ly = e.ly !== undefined ? e.ly : cy(A) - 8;
        text({x:lx, y:ly, class:"elabel"}, e.lab, layer);
      }
      return {e, p};
    });
  }

  function drawNodes(onSelect, onHover) {
    const layer = el("g", {}, map);
    const els = {};
    NODES.forEach(n => {
      const g = el("g", {class:"node " + n.st, tabindex:"0", role:"button",
                         "aria-label": n.title || n.t}, layer);
      el("rect", {x:n.x, y:n.y, width:n.w, height:n.h, rx:3, class:"body"}, g);
      const hasChips = n.id === "s3p";
      text({x:n.x + n.w / 2, y:n.y + (hasChips ? 26 : 22), "text-anchor":"middle", class:"t"}, n.t, g);
      n.s.forEach((line, i) => {
        text({x:n.x + n.w / 2, y:n.y + (hasChips ? 44 : 40) + i * 15,
              "text-anchor":"middle", class:"s"}, line, g);
      });
      el("rect", {x:n.x, y:n.y, width:n.w, height:n.h, class:"hit"}, g);
      g.addEventListener("click", () => onSelect(n.id));
      g.addEventListener("keydown", ev => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onSelect(n.id); }
      });
      g.addEventListener("mouseenter", () => onHover(n.id));
      g.addEventListener("mouseleave", () => onHover(null));
      els[n.id] = g;
    });
    return els;
  }

  drawDefs();
  drawZones();
  drawNotes();
  drawGap();
  const edgeEls = drawEdges();
  const nodeEls = drawNodes(id => select(id), id => hover(id));
  /* Después de las cajas: los chips viven DENTRO de la caja del bucket, y el
     relleno opaco de un nodo pinta encima de todo lo dibujado antes. */
  drawPrefixChips();

  /* ============================ PANEL ============================ */

  const P = {
    chip:  document.getElementById("p-chip"),
    title: document.getElementById("p-title"),
    desc:  document.getElementById("p-desc"),
    dl:    document.getElementById("p-dl"),
    warn:  document.getElementById("p-warn"),
    hint:  document.getElementById("p-hint")
  };

  function select(id) {
    NODES.forEach(n => nodeEls[n.id].classList.toggle("sel", n.id === id));
    const n = byId[id];
    P.chip.className = "chip " + n.st;
    P.chip.textContent = D.STATE_LABEL[n.st];
    P.title.textContent = n.title || n.t;
    P.desc.textContent = n.desc || "";
    P.dl.innerHTML = "";
    for (const k in (n.kv || {})) {
      const dt = document.createElement("dt"); dt.textContent = k;
      const dd = document.createElement("dd"); dd.textContent = n.kv[k];
      P.dl.append(dt, dd);
    }
    P.warn.innerHTML = "";
    if (n.warn) {
      const d = document.createElement("div");
      d.className = "warn" + (n.warn.k === "p" ? " p" : "");
      d.textContent = n.warn.t;
      P.warn.appendChild(d);
    }
    P.hint.textContent = "Esc limpia la selección.";
  }

  function clearSel() {
    NODES.forEach(n => nodeEls[n.id].classList.remove("sel"));
    P.chip.className = "chip";
    P.chip.textContent = D.IDLE.chip;
    P.title.textContent = D.IDLE.title;
    P.desc.textContent = D.IDLE.desc;
    P.dl.innerHTML = "";
    P.warn.innerHTML = "";
  }

  document.addEventListener("keydown", e => { if (e.key === "Escape") clearSel(); });

  function hover(id) {
    if (running) return;
    if (!id) { edgeEls.forEach(({p}) => p.classList.remove("lit", "dim")); return; }
    edgeEls.forEach(({e, p}) => {
      const on = e.a === id || e.b === id;
      p.classList.toggle("lit", on);
      p.classList.toggle("dim", !on);
    });
  }

  /* ============================ ALTERNADORES ============================ */

  const tp = document.getElementById("tgl-spot");
  const tb = document.getElementById("tgl-bad");

  /* Los dos alternadores son focos sobre el mismo lienzo, así que se excluyen:
     encender uno apaga el otro, en vez de dejar dos conjuntos de cajas atenuadas
     superpuestos y sin decir cuál manda. */
  function spotlight(btn, other, ids) {
    const on = btn.getAttribute("aria-pressed") === "true";
    btn.setAttribute("aria-pressed", String(!on));
    other.setAttribute("aria-pressed", "false");
    NODES.forEach(n => {
      nodeEls[n.id].classList.toggle("dim", !on && ids.indexOf(n.id) === -1);
    });
    edgeEls.forEach(({e, p}) => {
      const inside = ids.indexOf(e.a) !== -1 && ids.indexOf(e.b) !== -1;
      p.classList.toggle("dim", !on && !inside);
    });
  }

  tp.addEventListener("click", () => spotlight(tp, tb, D.SPOT));
  tb.addEventListener("click", () => spotlight(tb, tp, D.BAD));

  /* ============================ LA CORRIDA ============================ */

  const RUN = D.RUN;
  const btn = document.getElementById("play");
  const rstep = document.getElementById("runstep");
  const rtext = document.getElementById("runtext");
  const IDLE_STEP = rstep.textContent;
  const IDLE_TEXT = rtext.textContent;
  let running = false, timer = null, idx = 0;

  function stopRun() {
    running = false;
    clearTimeout(timer);
    btn.textContent = "▶ Reproducir la corrida semanal";
    NODES.forEach(n => nodeEls[n.id].classList.remove("lit", "dim"));
    edgeEls.forEach(({p}) => p.classList.remove("lit", "dim"));
    rstep.textContent = IDLE_STEP;
    rtext.textContent = IDLE_TEXT;
  }

  function step() {
    if (idx >= RUN.length) { stopRun(); return; }
    const s = RUN[idx];
    NODES.forEach(n => {
      nodeEls[n.id].classList.toggle("lit", n.id === s.id);
      nodeEls[n.id].classList.toggle("dim", n.id !== s.id);
    });
    edgeEls.forEach(({p}) => p.classList.add("dim"));
    rstep.textContent = `PASO ${idx + 1}/${RUN.length}`;
    rtext.textContent = s.t;
    select(s.id);
    idx++;
    timer = setTimeout(step, 2600);
  }

  btn.addEventListener("click", () => {
    if (running) { stopRun(); return; }
    running = true;
    idx = 0;
    btn.textContent = "■ Detener";
    step();
  });
})(window.DIAGRAM_DATA);
