/* Extensión Uruguay — render e interacción de las dos vistas.
   Hermano de diagram.js, no una copia: aquel traza rutas fijas para un solo lienzo,
   este lee los puntos de paso de cada arista desde los datos, porque tiene dos
   lienzos con geometrías distintas. Los datos viven en diagram-uruguay.data.js. */
(function (VIEWS) {
  "use strict";

  if (!VIEWS) { throw new Error("diagram-uruguay.data.js no se cargó antes que diagram-uruguay.js"); }

  const SVG = "http://www.w3.org/2000/svg";
  const $ = id => document.getElementById(id);
  const map = $("map");

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

  /* El punto medio de un lado de la caja. */
  function anchor(n, side) {
    if (side === "t") return [n.x + n.w / 2, n.y];
    if (side === "b") return [n.x + n.w / 2, n.y + n.h];
    if (side === "l") return [n.x, n.y + n.h / 2];
    return [n.x + n.w, n.y + n.h / 2];
  }

  /* ap/bp fijan los extremos a mano; via son los codos. Sin nada de eso, una
     arista izquierda→derecha a la misma altura es recta y, si no, hace un codo
     en la mitad del hueco. */
  function points(e, byId) {
    const A = byId[e.a], B = byId[e.b];
    const from = e.from || "r", to = e.to || "l";
    const p0 = e.ap || anchor(A, from);
    const p1 = e.bp || anchor(B, to);
    if (e.via) return [p0, ...e.via, p1];
    if (p0[0] === p1[0] || p0[1] === p1[1]) return [p0, p1];
    if (from === "r" || from === "l") {
      const mx = (p0[0] + p1[0]) / 2;
      return [p0, [mx, p0[1]], [mx, p1[1]], p1];
    }
    const my = (p0[1] + p1[1]) / 2;
    return [p0, [p0[0], my], [p1[0], my], p1];
  }

  const MARKERS = [["mk-flow", "var(--flow)"], ["mk-pend", "var(--pending)"],
                   ["mk-man", "var(--muted)"], ["mk-bad", "var(--breach)"]];
  const markerFor = k => k === "pend" ? "mk-pend" : k === "manual" ? "mk-man"
                       : k === "blocked" ? "mk-bad" : "mk-flow";

  /* ============================ ESTADO ============================ */

  let V = null;            // vista actual
  let byId = {}, nodeEls = {}, edgeEls = [];
  let running = false, timer = null, idx = 0;

  const P = {chip:$("p-chip"), title:$("p-title"), desc:$("p-desc"), dl:$("p-dl"),
             warn:$("p-warn"), hint:$("p-hint")};
  const playBtn = $("play"), rstep = $("runstep"), rtext = $("runtext");
  const toggles = [$("tgl-a"), $("tgl-b")];

  /* ============================ RENDER ============================ */

  function render(view) {
    V = view;
    map.innerHTML = "";
    map.setAttribute("viewBox", V.viewBox);
    byId = {};
    V.NODES.forEach(n => { byId[n.id] = n; });

    const defs = el("defs", {}, map);
    MARKERS.forEach(([id, c]) => {
      const m = el("marker", {id, viewBox:"0 0 10 10", refX:"9", refY:"5", markerWidth:"7",
                              markerHeight:"7", orient:"auto-start-reverse"}, defs);
      el("path", {d:"M0 0 L10 5 L0 10 z", fill:c}, m);
    });

    V.ZONES.forEach(z => {
      el("rect", {x:z.x, y:z.y, width:z.w, height:z.h, rx:4, class:"zone " + z.cls}, map);
      if (z.label) text({x:z.x + 16, y:z.y + 22, class:"ztext", fill:z.color}, z.label, map);
    });

    (V.NOTES || []).forEach(n => {
      const t = text({x:n.x, y:n.y, "font-family":"var(--mono)", "font-size":"10",
                      fill:n.color || "var(--muted)"}, n.t, map);
      if (n.weight) t.setAttribute("font-weight", n.weight);
    });

    const elayer = el("g", {}, map);
    edgeEls = V.EDGES.map(e => {
      const pts = points(e, byId);
      const cls = "edge" + (e.k ? " " + e.k : "");
      const p = el("path", {d:"M " + pts.map(q => q.join(" ")).join(" L "), class:cls,
                            "marker-end":`url(#${markerFor(e.k)})`}, elayer);
      if (e.k === "blocked") {
        const [x, y] = e.xm || pts[Math.floor(pts.length / 2)];
        el("line", {x1:x - 8, y1:y - 8, x2:x + 8, y2:y + 8, class:"xmark"}, elayer);
        el("line", {x1:x + 8, y1:y - 8, x2:x - 8, y2:y + 8, class:"xmark"}, elayer);
      }
      if (e.lab) text({x:e.lx, y:e.ly, class:"elabel"}, e.lab, elayer);
      return {e, p};
    });

    const nlayer = el("g", {}, map);
    nodeEls = {};
    V.NODES.forEach(n => {
      const g = el("g", {class:"node " + n.st, tabindex:"0", role:"button",
                         "aria-label":n.title || n.t}, nlayer);
      el("rect", {x:n.x, y:n.y, width:n.w, height:n.h, rx:3, class:"body"}, g);
      const chips = n.chips || [];
      text({x:n.x + n.w / 2, y:n.y + (chips.length ? 26 : 22), "text-anchor":"middle", class:"t"}, n.t, g);
      n.s.forEach((line, i) => {
        text({x:n.x + n.w / 2, y:n.y + 40 + i * 15, "text-anchor":"middle", class:"s"}, line, g);
      });
      /* Los chips van dentro de la caja, a lo ancho, al pie. */
      if (chips.length) {
        const gap = 8, cw = (n.w - 24 - gap * (chips.length - 1)) / chips.length;
        const cy = n.y + n.h - 56;
        chips.forEach((c, i) => {
          const x = n.x + 12 + i * (cw + gap);
          el("rect", {x, y:cy, width:cw, height:44, rx:2, class:"chipbox " + c.st}, g);
          text({x:x + cw / 2, y:cy + 19, "text-anchor":"middle", class:"chipk " + c.st}, c.k, g);
          text({x:x + cw / 2, y:cy + 35, "text-anchor":"middle", class:"chipv"}, c.v, g);
        });
      }
      el("rect", {x:n.x, y:n.y, width:n.w, height:n.h, class:"hit"}, g);
      g.addEventListener("click", () => select(n.id));
      g.addEventListener("keydown", ev => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(n.id); }
      });
      g.addEventListener("mouseenter", () => hover(n.id));
      g.addEventListener("mouseleave", () => hover(null));
      nodeEls[n.id] = g;
    });

    /* Textos de la página que dependen de la vista. */
    document.title = V.title;
    $("h-title").textContent = V.title;
    $("h-lede").textContent = V.lede;
    const meta = $("h-meta");
    meta.innerHTML = "";
    V.meta.forEach((m, i) => {
      if (i) { const s = document.createElement("span"); s.textContent = "·"; meta.appendChild(s); }
      const s = document.createElement("span"); s.textContent = m; meta.appendChild(s);
    });
    const keys = $("keys");
    keys.innerHTML = "";
    V.legend.forEach(([st, label]) => {
      const k = document.createElement("span"); k.className = "key";
      const sw = document.createElement("span"); sw.className = "sw " + st;
      k.append(sw, document.createTextNode(label));
      keys.appendChild(k);
    });
    toggles.forEach((b, i) => {
      b.textContent = V.toggles[i].label;
      b.setAttribute("aria-pressed", "false");
    });
    map.setAttribute("aria-label", V.title + ". " + V.lede);
    document.querySelectorAll("[data-view-only]").forEach(d => {
      d.hidden = d.getAttribute("data-view-only") !== V.key;
    });
    stopRun();
    clearSel();
  }

  /* ============================ PANEL ============================ */

  function select(id) {
    V.NODES.forEach(n => nodeEls[n.id].classList.toggle("sel", n.id === id));
    const n = byId[id];
    P.chip.className = "chip " + n.st;
    P.chip.textContent = V.STATE_LABEL[n.st];
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
    V.NODES.forEach(n => nodeEls[n.id].classList.remove("sel"));
    P.chip.className = "chip";
    P.chip.textContent = V.IDLE.chip;
    P.title.textContent = V.IDLE.title;
    P.desc.textContent = V.IDLE.desc;
    P.dl.innerHTML = "";
    P.warn.innerHTML = "";
    P.hint.innerHTML = "Atajo: <b>Esc</b> limpia la selección.";
  }

  function hover(id) {
    if (running) return;
    edgeEls.forEach(({e, p}) => {
      const on = id && (e.a === id || e.b === id);
      p.classList.toggle("lit", !!on);
      p.classList.toggle("dim", !!id && !on);
    });
  }

  /* Los dos focos se excluyen: encender uno apaga el otro. */
  function spotlight(i) {
    const btn = toggles[i], other = toggles[1 - i];
    const on = btn.getAttribute("aria-pressed") === "true";
    btn.setAttribute("aria-pressed", String(!on));
    other.setAttribute("aria-pressed", "false");
    const ids = V.toggles[i].ids;
    V.NODES.forEach(n => nodeEls[n.id].classList.toggle("dim", !on && ids.indexOf(n.id) === -1));
    edgeEls.forEach(({e, p}) => {
      const inside = ids.indexOf(e.a) !== -1 && ids.indexOf(e.b) !== -1;
      p.classList.toggle("dim", !on && !inside);
    });
  }
  toggles.forEach((b, i) => b.addEventListener("click", () => spotlight(i)));

  /* ============================ LA CORRIDA ============================ */

  const IDLE_STEP = rstep.textContent;

  function stopRun() {
    running = false;
    clearTimeout(timer);
    playBtn.textContent = V.play;
    V.NODES.forEach(n => nodeEls[n.id].classList.remove("lit", "dim"));
    edgeEls.forEach(({p}) => p.classList.remove("lit", "dim"));
    rstep.textContent = IDLE_STEP;
    rtext.textContent = "Pulsá «" + V.play.replace("▶ ", "") + "» para seguir el dato paso a paso.";
  }

  function step() {
    if (idx >= V.RUN.length) { stopRun(); return; }
    const s = V.RUN[idx];
    V.NODES.forEach(n => {
      nodeEls[n.id].classList.toggle("lit", n.id === s.id);
      nodeEls[n.id].classList.toggle("dim", n.id !== s.id);
    });
    edgeEls.forEach(({p}) => p.classList.add("dim"));
    rstep.textContent = `PASO ${idx + 1}/${V.RUN.length}`;
    rtext.textContent = s.t;
    select(s.id);
    idx++;
    timer = setTimeout(step, 3200);
  }

  playBtn.addEventListener("click", () => {
    if (running) { stopRun(); return; }
    running = true;
    idx = 0;
    playBtn.textContent = "■ Detener";
    step();
  });

  document.addEventListener("keydown", e => { if (e.key === "Escape") clearSel(); });

  /* ============================ PESTAÑAS ============================ */

  const tabs = Array.from(document.querySelectorAll("[role=tab]"));

  function show(key, focus) {
    const view = VIEWS[key] || VIEWS.local;
    tabs.forEach(t => {
      const on = t.dataset.view === view.key;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      if (on && focus) t.focus();
    });
    render(view);
    if (location.hash.slice(1) !== view.key) history.replaceState(null, "", "#" + view.key);
  }

  tabs.forEach((t, i) => {
    t.addEventListener("click", () => show(t.dataset.view));
    t.addEventListener("keydown", ev => {
      if (ev.key !== "ArrowRight" && ev.key !== "ArrowLeft") return;
      const next = tabs[(i + (ev.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      show(next.dataset.view, true);
    });
  });
  window.addEventListener("hashchange", () => show(location.hash.slice(1)));

  show(location.hash.slice(1) || "local");
})(window.DIAGRAM_UY);
