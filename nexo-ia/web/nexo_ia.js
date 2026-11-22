/* NEXO OBRA · capa de IA integrada en el panel (lo inyecta servidor.py; el index.html del repo no cambia).
   Se engancha a las funciones del panel: pControl, pParte, pValorizaciones, pConfig, resaltar, ir, cargarDatos. */
(function () {
  "use strict";
  const $q = s => document.querySelector(s);
  const e_ = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const sol = x => x == null ? "—" : "S/ " + Number(x).toLocaleString("es-PE", {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const num = (x, d = 2) => Number(x).toLocaleString("es-PE", {minimumFractionDigits: d, maximumFractionDigits: d});
  const IA = {aud: null, estado: null, filtro: "", abiertos: {}, narr: {}, parte: null, verTodos: false};
  async function pide(ruta, cuerpo) {
    const r = await fetch(ruta, cuerpo ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(cuerpo)} : {});
    const j = await r.json().catch(() => ({ok: false, error: "respuesta no válida"}));
    if (!r.ok || j.ok === false) throw new Error(j.error || "HTTP " + r.status);
    return j;
  }
  const aviso = m => { try { if (typeof toast === "function") toast(m); } catch (_) {} };
  const escribe = () => !IA.estado || IA.estado.puede_escribir;
  const usuario = () => { let u = localStorage.getItem("nexoIA_usuario"); if (!u) { u = prompt("Tu nombre (queda en la bitácora de decisiones):") || "anónimo"; localStorage.setItem("nexoIA_usuario", u); } return u; };

  /* ---------------------------------------------------------------- estilos */
  const css = document.createElement("style");
  css.textContent = `
  .ia-badge{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;font-weight:600;letter-spacing:.3px;padding:2px 8px;border-radius:999px;background:linear-gradient(90deg,rgba(229,184,105,.18),rgba(37,99,235,.18));border:1px solid rgba(229,184,105,.5);color:var(--gold)}
  .ia-met{font-size:10px;padding:1px 6px;border-radius:5px;border:1px solid var(--bd2);color:var(--tx2)}
  .ia-met.ml{border-color:#8b5cf6;color:#c4b5fd}.ia-met.det{border-color:var(--cob,#2563eb);color:#93c5fd}
  .ia-chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 10px}
  .ia-chip{cursor:pointer;border:1px solid var(--bd2);border-radius:9px;padding:6px 10px;background:var(--elev);min-width:120px}
  .ia-chip.on{border-color:var(--gold);box-shadow:0 0 0 1px var(--gold) inset}
  .ia-chip b{display:block;font-size:15px}.ia-chip span{font-size:11px;color:var(--mut)}
  .ia-h{border-top:1px solid var(--bd);padding:9px 2px}.ia-h:first-child{border-top:0}
  .ia-fila{display:flex;gap:8px;align-items:flex-start}.ia-fila .t{flex:1;min-width:0}
  .ia-acc{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
  .ia-caja{margin-top:8px;padding:10px 12px;border-radius:8px;background:var(--bg);border:1px solid var(--bd);font-size:12.5px;line-height:1.5}
  .ia-caja .lbl{font-size:10.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.4px;margin-top:6px}
  .ia-kv{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;font-size:11.5px;margin-top:4px}.ia-kv div:nth-child(odd){color:var(--mut)}
  .ia-ok{color:#86efac}.ia-mal{color:#fca5a5}
  .ia-txt{width:100%;min-height:74px;resize:vertical;background:var(--bg);color:var(--tx);border:1px solid var(--bd2);border-radius:8px;padding:9px;font:inherit}
  .ia-ej{cursor:pointer;font-size:11px;border:1px dashed var(--bd2);border-radius:999px;padding:2px 9px;color:var(--tx2)}
  .ia-sem{display:flex;gap:14px;align-items:center;flex-wrap:wrap}
  .ia-dec{font-size:10.5px;padding:1px 7px;border-radius:999px}.ia-dec.aceptado{background:rgba(22,163,74,.18);color:#86efac}.ia-dec.descartado{background:rgba(148,163,184,.15);color:var(--mut)}
  `;
  document.head.appendChild(css);

  /* ---------------------------------------------------------------- contenedores dentro de las páginas existentes */
  function slot(pagina, id, html, antesDe = ".grid") {
    let el = document.getElementById(id);
    if (!el) {
      const pag = $q("#pag-" + pagina); if (!pag) return null;
      el = document.createElement("div"); el.id = id; el.className = "card"; el.style.marginBottom = "14px";
      el.innerHTML = html;
      const ref = pag.querySelector(antesDe); pag.insertBefore(el, ref || pag.firstChild);
    }
    return el;
  }

  /* ================================================================ AUDITOR (página Control) */
  async function cargarAuditoria(forzar) {
    if (IA.aud && !forzar) return IA.aud;
    IA.aud = await pide("/api/ia/auditoria");
    return IA.aud;
  }
  function metodo(h) {
    return h.metodo === "machine learning" ? `<span class="ia-met ml">ML · ${Math.round((h.confianza || 0) * 100)} %</span>` : `<span class="ia-met det">regla</span>`;
  }
  function sev(h) { return `<span class="tag ${h.severidad === "alta" ? "bad" : h.severidad === "media" ? "warn" : ""}">${h.severidad}</span>`; }

  async function pintarAuditoria() {
    const box = slot("control", "iaAuditoria", `<div class="fila" style="margin:0;justify-content:space-between;gap:10px;flex-wrap:wrap">
        <h3 style="margin:0">Auditoría previa al cierre de la valorización <span class="ia-badge">✦ IA</span></h3>
        <span class="nota" id="iaAudMeta" style="margin:0"></span></div><div id="iaAudCuerpo"><div class="vacio">Auditando el modelo…</div></div>`);
    if (!box) return;
    let a;
    try { a = await cargarAuditoria(); } catch (err) { $q("#iaAudCuerpo").innerHTML = `<div class="vacio">No se pudo auditar: ${e_(err.message)}</div>`; return; }
    const pend = a.hallazgos.filter(h => !h.decision || h.decision.decision === "pendiente").length;
    $q("#iaAudMeta").innerHTML = `Datos v.${e_(a.version_datos)} · ${a.hallazgos.length} hallazgos · ${pend} sin revisar · <a href="#" id="iaRe">recalcular</a>`;
    $q("#iaRe").onclick = ev => { ev.preventDefault(); IA.aud = null; pintarAuditoria(); };
    const reglas = Object.entries(a.resumen);
    const sobre = a.hallazgos.filter(h => (h.impacto_soles || 0) > 0).reduce((s, h) => s + h.impacto_soles, 0);
    let h = `<div class="ia-chips">
      <div class="ia-chip ${IA.filtro ? "" : "on"}" data-f=""><b>${sol(sobre)}</b><span>costo directo en riesgo (sobremedición)</span></div>` +
      reglas.map(([k, r]) => `<div class="ia-chip ${IA.filtro === k ? "on" : ""}" data-f="${k}"><b>${r.n} <small style="font-size:11px;font-weight:400">${k}</small></b><span>${e_(r.nombre)}${r.impacto_soles ? " · " + sol(r.impacto_soles) : ""}</span></div>`).join("") + `</div>`;
    const lista = a.hallazgos.filter(x => !IA.filtro || x.regla === IA.filtro);
    const vis = IA.verTodos ? lista : lista.slice(0, 12);
    h += vis.map(x => filaHallazgo(x)).join("") || '<div class="vacio">Sin hallazgos.</div>';
    if (lista.length > vis.length) h += `<div style="text-align:center;margin-top:8px"><button class="btn sm" id="iaMas">Ver los ${lista.length} hallazgos</button></div>`;
    if (a.modelos && a.modelos.ML1) h += tarjetaModelo(a.modelos.ML1);
    $q("#iaAudCuerpo").innerHTML = h;
    box.querySelectorAll(".ia-chip").forEach(c => c.onclick = () => { IA.filtro = c.dataset.f; IA.verTodos = false; pintarAuditoria(); });
    if ($q("#iaMas")) $q("#iaMas").onclick = () => { IA.verTodos = true; pintarAuditoria(); };
    box.querySelectorAll("[data-acc]").forEach(b => b.onclick = () => accion(b.dataset.acc, b.dataset.id));
  }

  function filaHallazgo(x) {
    const d = x.decision && x.decision.decision !== "pendiente" ? `<span class="ia-dec ${x.decision.decision}">${x.decision.decision} · ${e_(x.decision.usuario)}</span>` : "";
    const n = IA.narr[x.id];
    let det = "";
    if (IA.abiertos[x.id]) {
      const v = x.evidencia.valores, kv = Object.entries(v).filter(([, y]) => typeof y !== "object" || y === null)
        .map(([k, y]) => `<div>${e_(k)}</div><div>${e_(typeof y === "number" ? num(y, Math.abs(y) < 10 ? 4 : 2) : y)}</div>`).join("");
      const extra = Object.entries(v).filter(([, y]) => y && typeof y === "object")
        .map(([k, y]) => `<div class="lbl">${e_(k)}</div><div style="font-size:11.5px">${Array.isArray(y) ? y.map(z => e_(typeof z === "object" ? JSON.stringify(z) : z)).join("<br>") : e_(JSON.stringify(y))}</div>`).join("");
      det = `<div class="ia-caja">${n ? narracion(n) : `<div class="nota" style="margin:0">Pulsa «Redactar observación» para que la IA la escriba a partir de esta evidencia.</div>`}
        <div class="lbl">Trazabilidad</div><div class="ia-kv"><div>Fuente</div><div>${e_(x.evidencia.fuente)}</div><div>Fórmula</div><div>${e_(x.evidencia.formula)}</div>
        <div>Elementos</div><div>${x.elementos.length} (${x.elementos.slice(0, 6).join(", ")}${x.elementos.length > 6 ? "…" : ""})</div>${kv}</div>${extra}</div>`;
    }
    return `<div class="ia-h"><div class="ia-fila">${sev(x)}<div class="t"><div>${e_(x.titulo)}</div>
      <div class="nota" style="margin:2px 0 0">${metodo(x)} ${e_(x.regla)} · ${e_(x.nombre)}${x.partidas.length ? " · " + x.partidas.map(e_).join(", ") : ""} ${d}</div></div>
      <div style="text-align:right;white-space:nowrap"><b>${x.impacto_soles == null ? "" : sol(x.impacto_soles)}</b></div></div>
      <div class="ia-acc"><button class="btn sm" data-acc="3d" data-id="${x.id}">Ver en 3D</button>
      <button class="btn sm" data-acc="det" data-id="${x.id}">${IA.abiertos[x.id] ? "Ocultar" : "Evidencia"}</button>
      <button class="btn sm pri" data-acc="narrar" data-id="${x.id}">✦ Redactar observación</button>
      ${escribe() ? `<button class="btn sm" data-acc="aceptado" data-id="${x.id}">Aceptar en expediente</button>
      <button class="btn sm" data-acc="descartado" data-id="${x.id}">Descartar</button>` : ""}</div>${det}</div>`;
  }

  function narracion(n) {
    const v = n.verificacion, tot = v.numeros.length;
    const sello = n.origen === "llm" ? `<span class="ia-ok">✔ redactado por ${e_(n.proveedor)} · ${e_(n.modelo)}</span>` : `<span>redacción por plantilla (${e_(n.origen)})</span>`;
    const chk = v.ok ? `<span class="ia-ok">✔ ${tot} número${tot === 1 ? "" : "s"} verificado${tot === 1 ? "" : "s"} contra la evidencia</span>` : `<span class="ia-mal">✘ sin respaldo: ${v.sin_respaldo.map(e_).join(", ")}</span>`;
    return `<div class="lbl" style="margin-top:0">Observación</div><div>${e_(n.observacion)}</div>
      <div class="lbl">Acción</div><div>${e_(n.accion)}</div>
      <div class="lbl">Responsable</div><div>${e_(n.responsable)} · ${n.afecta_valorizacion ? "afecta la valorización" : "no afecta el monto a valorizar"}</div>
      <div class="nota">${sello} · ${chk}${n.cache ? " · desde caché" : ""} · entrada ${e_(n.huella_entrada)}</div>`;
  }

  function tarjetaModelo(m) {
    return `<div class="ia-caja" style="margin-top:14px"><b>Modelo de ML · segunda opinión geométrica</b> <span class="ia-met ml">${e_(m.modelo)}</span>
      <div class="ia-kv"><div>Aprende</div><div>${e_(m.objetivo)} a partir de ${e_(m.entrada)}</div>
      <div>Validación</div><div>${e_(m.validacion)}</div>
      <div>Resultado</div><div>exactitud ${num(m.exactitud * 100, 1)} % · F1 macro ${num(m.f1_macro, 3)} · ${m.n_elementos} elementos · ${m.n_clases} clases</div>
      <div>Más importa</div><div>${m.importancia_variables.slice(0, 5).map(([k, v]) => `${e_(k)} ${num(v * 100, 1)} %`).join(" · ")}</div>
      <div>Confusiones</div><div>${m.confusiones.map(([k, v]) => `${e_(k)} (${v})`).join(" · ")}</div>
      <div>Umbral</div><div>se reporta solo si P(otro grupo) ≥ ${num(m.umbral_hallazgo * 100, 0)} %; ALI↔LMA no se reporta (mismo sólido en Revit)</div>
      <div>Entrenado</div><div>${e_(m.entrenado)} · datos v.${e_(m.version_datos)}</div></div></div>`;
  }

  async function accion(acc, id) {
    const x = IA.aud.hallazgos.find(h => h.id === id); if (!x) return;
    if (acc === "3d") { ir("visor"); resaltar(x.elementos, x.regla + " · " + x.titulo.slice(0, 60)); return; }
    if (acc === "det") { IA.abiertos[id] = !IA.abiertos[id]; return pintarAuditoria(); }
    if (acc === "narrar") {
      IA.abiertos[id] = true; aviso("La IA está redactando la observación…");
      try { IA.narr[id] = await pide("/api/ia/narrar", {id}); } catch (err) { alert("No se pudo redactar: " + err.message); }
      return pintarAuditoria();
    }
    if (acc === "aceptado" || acc === "descartado") {
      const motivo = acc === "descartado" ? prompt("Motivo para descartar (queda en la bitácora):") : (IA.narr[id]?.observacion || "");
      if (acc === "descartado" && motivo === null) return;
      try { await pide("/api/ia/decision", {id, decision: acc, motivo, usuario: usuario()}); IA.aud = null; await pintarAuditoria(); aviso("Decisión registrada en la bitácora"); }
      catch (err) { alert(err.message); }
    }
  }

  /* ================================================================ PARTE DIARIO ASISTIDO */
  const EJEMPLOS = ["Hoy se vació columnas y placas del piso 3 sector A", "Encofrado del techo del piso 2 sector B al 50%",
    "Fierro de columnas y placas del piso 7 al 30% en el sector B; además encofrado de vigas chatas del techo del piso 7 sector B"];
  function pintarParte() {
    const box = slot("parte", "iaParte", `<div class="fila" style="margin:0 0 8px;justify-content:space-between"><h3 style="margin:0">Parte diario asistido <span class="ia-badge">✦ IA</span></h3>
        <label class="nota" style="margin:0">Fecha <input type="date" class="inp" id="iaFecha"></label></div>
      <textarea class="ia-txt" id="iaTexto" placeholder="Escribe (o dicta) lo que se hizo hoy, como en el cuaderno de obra…"></textarea>
      <div class="fila" style="margin:6px 0 0;gap:6px;flex-wrap:wrap">${EJEMPLOS.map((t, i) => `<span class="ia-ej" data-i="${i}">${e_(t.length > 48 ? t.slice(0, 46) + "…" : t)}</span>`).join("")}
        <span style="flex:1"></span>${"webkitSpeechRecognition" in window ? '<button class="btn sm" id="iaVoz">🎤 Dictar</button>' : ""}<button class="btn sm pri" id="iaInterp">✦ Interpretar</button></div>
      <div id="iaParteRes"></div>`, ".grid");
    if (!box || box.dataset.listo) return;
    box.dataset.listo = 1;
    $q("#iaFecha").value = (window.S && S.diaSel) || corte();
    box.querySelectorAll(".ia-ej").forEach(x => x.onclick = () => { $q("#iaTexto").value = EJEMPLOS[+x.dataset.i]; });
    $q("#iaInterp").onclick = interpretar;
    if ($q("#iaVoz")) $q("#iaVoz").onclick = () => { const r = new webkitSpeechRecognition(); r.lang = "es-PE"; r.onresult = ev => { $q("#iaTexto").value = ev.results[0][0].transcript; interpretar(); }; r.start(); aviso("Escuchando…"); };
  }

  async function interpretar() {
    const texto = $q("#iaTexto").value.trim(); if (!texto) return;
    $q("#iaParteRes").innerHTML = '<div class="vacio">Interpretando…</div>';
    try { IA.parte = await pide("/api/ia/parte", {texto, fecha: $q("#iaFecha").value}); } catch (err) { $q("#iaParteRes").innerHTML = `<div class="vacio">${e_(err.message)}</div>`; return; }
    pintarResultadoParte();
  }

  function pintarResultadoParte(sim) {
    const p = IA.parte; if (!p) return;
    let h = `<div class="nota">Interpretado por <b>${e_(p.origen === "llm" ? p.proveedor + " · " + p.modelo : p.origen)}</b> · datos v.${e_(p.version_datos)} · las cantidades salen del modelo (saldo de cada elemento × %), no del intérprete.</div>`;
    if (!p.resumen.length) h += '<div class="vacio">No se identificó ningún trabajo para registrar.</div>';
    h += p.resumen.map((r, i) => `<div class="ia-caja"><div class="ia-fila"><div class="t"><b>${e_(r.paquete)} · sector ${e_(r.sector)} · ${e_(r.clase)} · ${num(r.porcentaje, 0)} %</b>
        <div class="nota" style="margin:2px 0 0">«${e_(r.texto_origen || "")}» → ${r.grupos.map(e_).join(", ")} · ${r.n_elementos} elementos${r.sin_saldo ? ` · ${r.sin_saldo} ya completos` : ""}</div></div>
        <button class="btn sm" data-ver="${i}">Ver en 3D</button></div>
        <table style="margin-top:6px"><tbody>${r.partidas.map(x => `<tr><td>${e_(x.item)} <span class="nota">${e_(x.desc)}</span></td><td class="n">${num(x.cantidad, 3)} ${e_(x.und)}</td><td class="n">${sol(x.monto)}</td></tr>`).join("")}</tbody></table></div>`).join("");
    if (p.intencion.dudas && p.intencion.dudas.length) h += `<div class="ia-caja"><div class="lbl" style="margin-top:0">Para revisar (no se registra)</div>${p.intencion.dudas.map(d => `<div>• ${e_(d)}</div>`).join("")}</div>`;
    if (p.problemas.length) h += `<div class="ia-caja ia-mal">${p.problemas.map(e_).join("<br>")}</div>`;
    if (sim) h += `<div class="ia-caja"><div class="lbl" style="margin-top:0">Validación del sistema (simulación, no se guardó)</div>
        <div>${sim.aplicados.length} valores aceptados · ${sim.rechazados.length} rechazados</div>
        ${sim.alertas.length ? `<div class="ia-mal">${sim.alertas.slice(0, 8).map(e_).join("<br>")}</div>` : '<div class="ia-ok">✔ sin alertas de mayor metrado</div>'}
        ${sim.rechazados.slice(0, 5).map(r => `<div class="ia-mal">${e_(r.id)} ${e_(r.item)}: ${e_(r.motivo)}</div>`).join("")}</div>`;
    if (p.registros.length) h += `<div class="fila" style="margin-top:10px;gap:8px;justify-content:flex-end"><b style="flex:1">Total del parte: ${sol(p.monto_total)} · ${p.registros.length} valores</b>
        <button class="btn sm" id="iaSim">Validar con el sistema</button>${!escribe() ? "" : `<button class="btn sm pri" id="iaReg" ${sim ? "" : "disabled title='Primero valida'"}>Registrar ${e_(fmtD(p.fecha))}</button>`}</div>`;
    $q("#iaParteRes").innerHTML = h;
    $q("#iaParteRes").querySelectorAll("[data-ver]").forEach(b => b.onclick = () => { const r = p.resumen[+b.dataset.ver]; ir("visor"); resaltar(r.elementos, `${r.paquete} ${r.sector} · ${r.clase}`); });
    if ($q("#iaSim")) $q("#iaSim").onclick = async () => { try { pintarResultadoParte(await pide("/api/metrado", {fecha: p.fecha, simular: true, registros: p.registros})); } catch (err) { alert(err.message); } };
    if ($q("#iaReg")) $q("#iaReg").onclick = async () => {
      if (!confirm(`Se registrarán ${p.registros.length} valores (${sol(p.monto_total)}) con fecha ${fmtD(p.fecha)}. ¿Continuar?`)) return;
      try { const r = await pide("/api/metrado", {fecha: p.fecha, simular: false, registros: p.registros, origen: "ia-parte-diario"});
        IA.parte = null; IA.aud = null; $q("#iaParteRes").innerHTML = `<div class="ia-caja ia-ok">✔ Registrado: ${r.aplicados.length} valores. Queda en la bitácora con el texto original.</div>`;
        S.diaSel = p.fecha; await cargarDatos(); } catch (err) { alert("No se pudo registrar: " + err.message); } };
  }

  /* ================================================================ SEMÁFORO (Valorizaciones) */
  async function pintarSemaforo() {
    const box = slot("valorizaciones", "iaSemaforo", `<div class="ia-sem" id="iaSemC"><span class="nota">Auditando…</span></div>`);
    if (!box) return;
    try {
      const a = await cargarAuditoria();
      const pend = a.hallazgos.filter(h => !h.decision), alta = pend.filter(h => h.severidad === "alta");
      const acept = a.hallazgos.filter(h => h.decision && h.decision.decision === "aceptado");
      const color = alta.length ? "bad" : pend.length ? "warn" : "ok";
      $q("#iaSemC").innerHTML = `<span class="ia-badge">✦ IA</span><span class="tag ${color}" style="font-size:12px;padding:3px 10px">${alta.length ? "No cerrar todavía" : pend.length ? "Cerrar con observaciones" : "Listo para cerrar"}</span>
        <span>${alta.length} críticos · ${pend.length} sin revisar · ${acept.length} aceptados para el expediente</span><span style="flex:1"></span>
        <button class="btn sm" id="iaIrCtrl">Revisar en Control</button>`;
      $q("#iaIrCtrl").onclick = () => ir("control");
    } catch (err) { $q("#iaSemC").innerHTML = `<span class="nota">${e_(err.message)}</span>`; }
  }

  /* ================================================================ TRAZABILIDAD (Configuración) */
  async function pintarTraza() {
    const box = slot("config", "iaTraza", `<h3>Trazabilidad de la IA <span class="ia-badge">✦ IA</span></h3><div id="iaTrazaC"></div>`);
    if (!box) return;
    try {
      const [st, b] = await Promise.all([pide("/api/ia/estado"), pide("/api/ia/bitacora?n=15")]);
      IA.estado = st;
      $q("#iaTrazaC").innerHTML = `<div class="ia-kv"><div>Modelo</div><div>${e_(st.modelo.id)} · versión ${e_(st.modelo.version)} · ${e_(st.modelo.origen)}</div>
        <div>LLM</div><div>${e_(st.llm.proveedor)} · ${e_(st.llm.modelo)}${st.llm_activo ? "" : " (sin modelo: plantillas)"}</div>
        <div>Versión de datos</div><div>${e_(st.huellas.version_datos)} (${Object.entries(st.huellas).filter(([k]) => k !== "version_datos").map(([k, v]) => e_(k) + " " + e_(v)).join(" · ")})</div>
        <div>Permiso</div><div>${st.puede_escribir ? "puedes registrar y decidir" : "solo lectura"}</div>
        <div>Hacia Revit</div><div><a href="/api/registros.json">descargar registros (formato del complemento)</a></div></div>
        <div class="lbl" style="margin-top:10px">Últimos eventos · <a href="/api/ia/bitacora.jsonl" download="bitacora_ia.jsonl">descargar bitácora completa</a></div>
        <table><tbody>${b.eventos.reverse().map(ev => `<tr><td class="nota">${e_(ev.ts.replace("T", " "))}</td><td>${e_(ev.tarea)}</td><td>${e_(ev.hallazgo || ev.texto || ev.decision || "")}</td><td class="nota">${e_(ev.origen || ev.usuario || "")}</td></tr>`).join("")}</tbody></table>`;
    } catch (err) { $q("#iaTrazaC").innerHTML = e_(err.message); }
  }

  /* ================================================================ enganche con el panel */
  function envolver(nombre, extra) {
    const orig = window[nombre] || eval(nombre);            // las funciones del panel son globales
    const nueva = function () { const r = orig.apply(this, arguments); try { extra(); } catch (err) { console.error("[IA]", err); } return r; };
    try { eval(nombre + " = nueva"); } catch (err) { console.error("[IA] no se pudo enganchar " + nombre, err); }
  }
  envolver("pControl", pintarAuditoria);
  envolver("pParte", pintarParte);
  envolver("pValorizaciones", pintarSemaforo);
  envolver("pConfig", pintarTraza);
  /* ================================================================ SELECTOR DE MODELO Y VERSIÓN (cabecera) */
  async function selectorModelo() {
    let r; try { r = await pide("/api/modelos"); } catch (_) { return; }
    const hdr = document.querySelector("header"), sp = hdr && hdr.querySelector(".sp"); if (!hdr) return;
    const actual = r.actual, m = r.modelos.find(x => x.id === actual.id);
    const el = document.createElement("label"); el.className = "campo"; el.style.marginLeft = "10px";
    el.innerHTML = `Modelo <select class="inp" id="iaModelo">${r.modelos.map(x => `<option value="${e_(x.id)}" ${x.id === actual.id ? "selected" : ""}>${e_(x.nombre)}</option>`).join("")}</select>
      <select class="inp" id="iaVersion" title="Versión publicada desde Revit">${(m ? m.versiones : []).map((v, i) => `<option value="${e_(v.version)}" ${v.version === actual.version ? "selected" : ""}>${e_(v.version)}${i === 0 ? " · vigente" : ""}</option>`).join("")}</select>`;
    hdr.insertBefore(el, sp ? sp.nextSibling : null);
    const cambiar = (mid, ver) => {
      document.cookie = `nexo_modelo=${encodeURIComponent(mid)}; path=/; max-age=2592000; samesite=lax`;
      document.cookie = ver ? `nexo_version=${encodeURIComponent(ver)}; path=/; max-age=2592000; samesite=lax` : "nexo_version=; path=/; max-age=0";
      location.reload();
    };
    $q("#iaModelo").onchange = ev => cambiar(ev.target.value, "");
    $q("#iaVersion").onchange = ev => cambiar(actual.id, ev.target.selectedIndex === 0 ? "" : ev.target.value);
    if (m && m.versiones[0].version !== actual.version) aviso(`Estás viendo la versión ${actual.version}; la vigente es ${m.versiones[0].version}`);
  }
  selectorModelo();
  pide("/api/ia/estado").then(st => { IA.estado = st; }).catch(() => {});
  if (typeof S !== "undefined" && S.datos) pintar();
})();
