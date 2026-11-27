/* NEXO OBRA · capa de IA integrada en el panel (lo inyecta servidor.py; el index.html del repo no cambia).
   Se engancha a las funciones del panel: pControl, pParte, pValorizaciones, pConfig, resaltar, ir, cargarDatos. */
(function () {
  "use strict";
  const $q = s => document.querySelector(s);
  const e_ = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const sol = x => x == null ? "—" : "S/ " + Number(x).toLocaleString("es-PE", {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const num = (x, d = 2) => Number(x).toLocaleString("es-PE", {minimumFractionDigits: d, maximumFractionDigits: d});
  const IA = {aud: null, estado: null, filtro: "", abiertos: {}, narr: {}, parte: null, verTodos: false, dron: null, dronSim: null, dronInf: false, ifc: null, desdeIfc: true};
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

  /* ================================================================ AVANCE POR DRON (nube de puntos vs. modelo) */
  const EST = {construido: ["Construido (medido)", "ok"], inferido: ["Inferido por secuencia", ""], dudoso: ["Dudoso · revisar", "warn"],
    no_construido: ["No construido", "bad"], no_observable: ["No observable", ""]};
  function pintarDron() {
    const box = slot("parte", "iaDron", `<div class="fila" style="margin:0 0 8px;justify-content:space-between;flex-wrap:wrap;gap:8px">
        <h3 style="margin:0">Avance por dron · nube de puntos vs. modelo <span class="ia-badge">✦ IA</span></h3>
        <span class="nota" id="iaDronMeta" style="margin:0"></span></div>
      <div class="fila" style="margin:0;gap:8px;flex-wrap:wrap;align-items:center">
        <label class="nota" style="margin:0">Fecha del vuelo <input type="date" class="inp" id="iaDronFecha"></label>
        <input type="file" id="iaDronArchivo" accept=".ply,.las,.laz,.xyz,.pts,.txt,.csv,.ifc" class="inp" style="max-width:260px">
        <button class="btn sm pri" id="iaDronSubir">✦ Procesar archivo</button>
        <button class="btn sm" id="iaDronDemo" title="Genera una nube desde el modelo con verdad conocida (avance según cronograma, atrasos y 2 registros falsos sembrados)">Probar con nube sintética</button></div>
      <div class="nota" style="margin:6px 0 0">Nube de WebODM (.laz/.ply) o de ReCap (.pts/.ply). Sube primero el <b>.ifc</b> del proyecto (exportado de Revit en coordenadas compartidas): con él la nube en UTM se convierte sola al modelo. Luego el sistema la alinea (ICP), mide cada elemento y propone el metrado; nada se registra sin tu confirmación.</div>
      <div id="iaIfc" class="nota" style="margin:6px 0 0"></div>
      <div class="fila" style="margin:8px 0 0"><button class="btn sm" id="iaDronVer" hidden>Ver la nube de puntos en 3D</button></div>
      <div id="iaNube"></div>
      <div id="iaDronRes"></div>`, ".grid");
    if (!box) return;
    if (!box.dataset.listo) {
      box.dataset.listo = 1;
      $q("#iaDronFecha").value = (window.S && S.diaSel) || corte();
      $q("#iaDronSubir").onclick = subirNube;
      $q("#iaDronDemo").onclick = demoNube;
      $q("#iaDronVer").onclick = abrirVisorNube;
      if (!IA.dron) pide("/api/ia/escaneo").then(r => { if (!r.vacio) { IA.dron = r; pintarResultadoDron(); } }).catch(() => {});
      pide("/api/ia/escaneo/ifc").then(g => { IA.ifc = g.vacio ? null : g; pintarIfc(); }).catch(() => {});
    }
    if (IA.dron) pintarResultadoDron();
  }

  function pintarIfc() {
    const g = IA.ifc, box = $q("#iaIfc"); if (!box) return;
    box.innerHTML = g ? `<span class="tag ok">IFC</span> <b>${e_(g.archivo)}</b> · ${g.elementos_comunes}/${g.elementos_panel} elementos cruzados por ElementId · giro ${num(g.giro_grados, 3)}° · residuo ${num(g.residuo_mediano_m * 1000, 1)} mm${g.n_no_calzan ? ` · ${g.n_no_calzan} no calzan` : ""} · ${Object.entries(g.solo_en_ifc || {}).map(([k, v]) => `${v} ${k.replace("Ifc", "")}`).join(", ")} solo en el IFC
      <label style="margin-left:10px"><input type="checkbox" id="iaDronDesdeIfc" ${IA.desdeIfc !== false ? "checked" : ""}> simular desde el IFC (nube en UTM, como WebODM)</label>`
      : "Sin IFC: la nube debe venir en coordenadas del modelo.";
    const c = $q("#iaDronDesdeIfc"); if (c) c.onchange = ev => IA.desdeIfc = ev.target.checked;
  }
  async function subirIfc(f) {
    $q("#iaDronRes").innerHTML = `<div class="vacio">Leyendo ${e_(f.name)} (${num(f.size / 1048576, 1)} MB), cruzando elementos y calculando la georreferencia (≈1 min)…</div>`;
    try {
      const r = await fetch(`/api/ia/escaneo/ifc?nombre=${encodeURIComponent(f.name)}`, {method: "POST", body: f});
      const j = await r.json(); if (!r.ok || j.ok === false) throw new Error(j.error || "HTTP " + r.status);
      IA.ifc = j; pintarIfc();
      $q("#iaDronRes").innerHTML = `<div class="ia-caja"><b>IFC cargado.</b> ${j.elementos_comunes} de ${j.elementos_panel} elementos del panel encontrados en el IFC; coordenadas compartidas → modelo con giro ${num(j.giro_grados, 3)}° y residuo mediano ${num(j.residuo_mediano_m * 1000, 1)} mm. Ahora prueba «Probar con nube sintética» o sube la nube del vuelo.</div>`;
      if (IA.dron) setTimeout(pintarResultadoDron, 4000);
    } catch (err) { $q("#iaDronRes").innerHTML = `<div class="vacio">${e_(err.message)}</div>`; }
  }
  async function subirNube() {
    const f = $q("#iaDronArchivo").files[0]; if (!f) { alert("Elige un archivo: nube de puntos o .ifc"); return; }
    if (/\.ifc$/i.test(f.name)) return subirIfc(f);
    $q("#iaDronRes").innerHTML = `<div class="vacio">Subiendo ${e_(f.name)} (${num(f.size / 1048576, 1)} MB) y comparando con el modelo…</div>`;
    try {
      const r = await fetch(`/api/ia/escaneo/subir?fecha=${encodeURIComponent($q("#iaDronFecha").value)}&nombre=${encodeURIComponent(f.name)}`, {method: "POST", body: f});
      const j = await r.json(); if (!r.ok || j.ok === false) throw new Error(j.error || "HTTP " + r.status);
      cerrarNube(); IA.dron = j; IA.dronSim = null; pintarResultadoDron();
    } catch (err) { $q("#iaDronRes").innerHTML = `<div class="vacio">${e_(err.message)}</div>`; }
  }
  async function demoNube() {
    $q("#iaDronRes").innerHTML = '<div class="vacio">Generando la nube sintética desde el modelo y comparándola (≈20 s)…</div>';
    try { cerrarNube(); IA.dron = await pide("/api/ia/escaneo/demo", {fecha: $q("#iaDronFecha").value, desde_ifc: !!IA.ifc && IA.desdeIfc !== false}); IA.dronSim = null; pintarResultadoDron(); }
    catch (err) { $q("#iaDronRes").innerHTML = `<div class="vacio">${e_(err.message)}</div>`; }
  }

  function pintarResultadoDron() {
    const d = IA.dron, sim = IA.dronSim; if (!d || !$q("#iaDronRes")) return;
    $q("#iaDronVer").hidden = !d.vista;
    const a = d.avance, al = d.alineacion || {}, inc = !!IA.dronInf;
    $q("#iaDronMeta").innerHTML = `${e_(d.nombre)} · ${num(d.parametros.puntos_nube, 0)} puntos · ${num(d.segundos, 1)} s · datos v.${e_(d.version_datos)}`;
    let h = `<div class="ia-chips"><div class="ia-chip on"><b>${num(a.total.avance_pct, 1)} %</b><span>avance físico (${num(a.total.construido_m3, 1)} de ${num(a.total.total_m3, 1)} m³ de concreto)</span></div>` +
      Object.entries(EST).map(([k, [t]]) => `<div class="ia-chip" data-est="${k}"><b>${a.conteo[k]}</b><span>${t}</span></div>`).join("") + `</div>`;
    h += `<div class="ia-kv"><div>Alineación ICP</div><div>${al.aplicada ? `desplazamiento ${al.traslacion_m.map(x => num(x, 3)).join(" / ")} m · giro ${num(al.giro_z_grados, 2)}° · residuo ${num(al.rmse_m * 100, 1)} cm · ${num(al.fraccion_emparejada * 100, 0)} % de puntos emparejados${al.georreferencia ? ` · <span class="tag ok">convertida desde coordenadas UTM/compartidas con el IFC (estaba a ${num(al.georreferencia.distancia_original_km, 0)} km del origen del modelo)</span>` : ""}${al.aviso ? ` <span class="ia-mal">⚠ ${e_(al.aviso)}</span>` : ""}` : "sin alinear"}</div>
      <div>Criterio</div><div>construido si ≥ ${num(d.parametros.cobertura_construido * 100, 0)} % de su parte visible tiene puntos a &lt; ${num(d.parametros.tolerancia_m * 100, 0)} cm; no se juzga lo que el dron no puede ver (&lt; ${num(d.parametros.min_fraccion_visible * 100, 0)} % visible)</div></div>`;
    if (d.metricas) {
      const m = d.metricas, x = m.alertas_valorizacion || {}, ea = m.error_alineacion || {};
      h += `<div class="ia-caja"><b>Validación contra la verdad conocida</b> <span class="ia-met det">nube sintética</span>
        <div class="ia-kv"><div>Exactitud</div><div><b>${num(m.exactitud * 100, 1)} %</b> en ${m.decididos} elementos decididos · precisión ${num(m.precision_construido * 100, 1)} % · exhaustividad ${num(m.exhaustividad_construido * 100, 1)} %</div>
        <div>Sin decidir</div><div>${m.sin_decidir.construido + m.sin_decidir.no_construido} (el sistema los marca para revisión en vez de adivinar)</div>
        <div>Alertas sembradas</div><div>${x.detectadas ?? "—"} de ${x.sembradas ?? "—"} detectadas · ${x.falsas_alarmas ?? 0} falsas alarmas</div>
        <div>Error de alineación</div><div>${ea.traslacion_m != null ? `${num(ea.traslacion_m * 100, 2)} cm · ${num(ea.giro_grados, 3)}°` : "—"}</div></div></div>`;
    }
    if (d.alertas_valorizacion.length) h += `<div class="ia-caja"><div class="lbl" style="margin-top:0">Registrado pero el dron no lo confirma (${d.alertas_valorizacion.length})</div>` +
      d.alertas_valorizacion.map((x, i) => `<div class="ia-fila" style="margin-top:6px"><span class="tag ${x.severidad === "alta" ? "bad" : "warn"}">${x.severidad}</span><div class="t">${e_(x.texto)}</div>
        <b style="white-space:nowrap">${sol(x.monto_registrado)}</b><button class="btn sm" data-alerta="${i}">Ver en 3D</button></div>`).join("") + `</div>`;
    h += `<table style="margin-top:10px"><thead><tr><th>Nivel</th><th class="n">Medido</th><th class="n">Inferido</th><th class="n">Dudoso</th><th class="n">No constr.</th><th class="n">No observ.</th><th class="n">Avance</th></tr></thead><tbody>` +
      a.por_nivel.map(n => `<tr><td>${e_(n.nivel)}</td><td class="n">${n.construido}</td><td class="n">${n.inferido}</td><td class="n">${n.dudoso}</td><td class="n">${n.no_construido}</td><td class="n">${n.no_observable}</td><td class="n">${num(n.avance_pct, 1)} %</td></tr>`).join("") + `</tbody></table>`;
    const res = d.resumen.concat(inc ? d.resumen_inferidos : []), regs = d.registros.concat(inc ? d.registros_inferidos : []);
    const total = d.monto_total + (inc ? d.monto_inferidos : 0);
    h += `<div class="lbl" style="margin-top:12px">Propuesta de registro: lo que el dron ve construido y aún no está registrado</div>`;
    if (!res.length) h += '<div class="vacio">Nada nuevo por registrar.</div>';
    h += res.map((r, i) => `<div class="ia-caja"><div class="ia-fila"><div class="t"><b>${e_(r.nivel)} · ${e_(r.nombre_grupo)}</b>
        <div class="nota" style="margin:2px 0 0">${r.n_elementos} elementos · ${e_(r.origen)}</div></div><button class="btn sm" data-res="${i}">Ver en 3D</button></div>
        <table style="margin-top:6px"><tbody>${r.partidas.map(x => `<tr><td>${e_(x.item)} <span class="nota">${e_(x.desc)}</span></td><td class="n">${num(x.cantidad, 3)} ${e_(x.und)}</td><td class="n">${sol(x.monto)}</td></tr>`).join("")}</tbody></table></div>`).join("");
    if (sim) h += `<div class="ia-caja"><div class="lbl" style="margin-top:0">Validación del sistema (simulación, no se guardó)</div>
        <div>${sim.aplicados.length} valores aceptados · ${sim.rechazados.length} rechazados</div>
        ${sim.alertas.length ? `<div class="ia-mal">${sim.alertas.slice(0, 8).map(e_).join("<br>")}</div>` : '<div class="ia-ok">✔ sin alertas de mayor metrado</div>'}</div>`;
    h += `<div class="fila" style="margin-top:10px;gap:8px;justify-content:flex-end;flex-wrap:wrap">
        <label class="nota" style="margin:0;flex:1"><input type="checkbox" id="iaDronInf" ${inc ? "checked" : ""}> incluir inferidos (${d.registros_inferidos.length} valores, ${sol(d.monto_inferidos)}): ocultos por lo construido encima</label>
        <b>${sol(total)} · ${regs.length} valores</b>${regs.length ? `<button class="btn sm" id="iaDronSim">Validar con el sistema</button>${escribe() ? `<button class="btn sm pri" id="iaDronReg" ${sim ? "" : "disabled title='Primero valida'"}>Registrar ${e_(fmtD(d.fecha))}</button>` : ""}` : ""}</div>`;
    $q("#iaDronRes").innerHTML = h;
    const R = $q("#iaDronRes");
    $q("#iaDron").querySelectorAll("[data-est]").forEach(c => c.onclick = () => { const ids = d.ids_por_estado[c.dataset.est]; if (!ids.length) return aviso("Ningún elemento en ese estado"); ir("visor"); resaltar(ids, "Dron · " + EST[c.dataset.est][0]); });
    R.querySelectorAll("[data-alerta]").forEach(b => b.onclick = () => { const x = d.alertas_valorizacion[+b.dataset.alerta]; ir("visor"); resaltar([x.id], "Dron · registrado y no visto"); });
    R.querySelectorAll("[data-res]").forEach(b => b.onclick = () => { const r = res[+b.dataset.res]; ir("visor"); resaltar(r.elementos, `Dron · ${r.nivel} ${r.nombre_grupo}`); });
    $q("#iaDronInf").onchange = ev => { IA.dronInf = ev.target.checked; IA.dronSim = null; pintarResultadoDron(); };
    if ($q("#iaDronSim")) $q("#iaDronSim").onclick = async () => { try { IA.dronSim = await pide("/api/metrado", {fecha: d.fecha, simular: true, registros: regs}); pintarResultadoDron(); } catch (err) { alert(err.message); } };
    if ($q("#iaDronReg")) $q("#iaDronReg").onclick = async () => {
      if (!confirm(`Se registrarán ${regs.length} valores (${sol(total)}) con fecha ${fmtD(d.fecha)} a partir del vuelo del dron. ¿Continuar?`)) return;
      try { const r = await pide("/api/metrado", {fecha: d.fecha, simular: false, registros: regs, origen: "ia-dron"});
        IA.dronSim = null; IA.aud = null; d.registros = []; d.registros_inferidos = []; d.resumen = []; d.resumen_inferidos = []; d.monto_total = d.monto_inferidos = 0;
        pintarResultadoDron(); aviso(`Registrado: ${r.aplicados.length} valores desde el vuelo`); S.diaSel = d.fecha; await cargarDatos(); }
      catch (err) { alert("No se pudo registrar: " + err.message); } };
  }

  /* ================================================================ VISOR DE LA NUBE (puntos del dron sobre el modelo) */
  const COL_EST = [[0.09, 0.64, 0.29], [0.13, 0.62, 0.72], [0.96, 0.62, 0.04], [0.86, 0.15, 0.15], [0.55, 0.6, 0.7], [0.85, 0.2, 0.85]];
  const NUBE = (() => {
    let cv, gl, pP, pM, bufs = {}, n = 0, rangos = [], cam = {th: -0.9, ph: 0.5, d: 60, t: [0, 0, 0]}, radio = 30, cfg = {modo: "rgb", malla: true, nube: true, tam: 2, zmax: 1e9}, colEl = {}, zr = [0, 1];
    const VS_P = `attribute vec3 p; attribute vec3 c; uniform mat4 mvp; uniform float sz; uniform float zmax; varying vec3 vc;
      void main(){ vc = c; gl_PointSize = sz; gl_Position = p.z > zmax ? vec4(2.0,2.0,2.0,1.0) : mvp * vec4(p,1.0); }`;
    const FS_P = `precision mediump float; varying vec3 vc; void main(){ gl_FragColor = vec4(vc,1.0); }`;
    const VS_M = `attribute vec3 p; attribute vec3 n; uniform mat4 mvp; uniform vec3 luz; varying float l; varying float z;
      void main(){ gl_Position = mvp * vec4(p,1.0); l = 0.5 + 0.5*abs(dot(normalize(n), luz)); z = p.z; }`;
    const FS_M = `precision mediump float; uniform vec4 col; uniform float zmax; varying float l; varying float z;
      void main(){ if(z > zmax) discard; gl_FragColor = vec4(col.rgb*l, col.a); }`;
    function prog(v, f) { const sh = (t, s) => { const x = gl.createShader(t); gl.shaderSource(x, s); gl.compileShader(x); return x; };
      const p = gl.createProgram(); gl.attachShader(p, sh(gl.VERTEX_SHADER, v)); gl.attachShader(p, sh(gl.FRAGMENT_SHADER, f)); gl.linkProgram(p); return p; }
    function persp(f, a, nn, l) { const t = 1 / Math.tan(f / 2); return [t / a, 0, 0, 0, 0, t, 0, 0, 0, 0, (l + nn) / (nn - l), -1, 0, 0, 2 * l * nn / (nn - l), 0]; }
    function mul(a, b) { const r = new Array(16); for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) { let s = 0; for (let k = 0; k < 4; k++) s += a[k * 4 + j] * b[i * 4 + k]; r[i * 4 + j] = s; } return r; }
    function mira(e, t) { let z = [e[0] - t[0], e[1] - t[1], e[2] - t[2]]; let L = Math.hypot(...z); z = z.map(x => x / L); let x = [-z[1], z[0], 0]; L = Math.hypot(...x) || 1; x = x.map(v => v / L);
      const y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]];
      return [x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -(x[0] * e[0] + x[1] * e[1] + x[2] * e[2]), -(y[0] * e[0] + y[1] * e[1] + y[2] * e[2]), -(z[0] * e[0] + z[1] * e[1] + z[2] * e[2]), 1]; }
    const ojo = () => [cam.t[0] + cam.d * Math.cos(cam.ph) * Math.cos(cam.th), cam.t[1] + cam.d * Math.cos(cam.ph) * Math.sin(cam.th), cam.t[2] + cam.d * Math.sin(cam.ph)];
    function buf(datos) { const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, datos, gl.STATIC_DRAW); return b; }
    function montar(contenedor) {
      if (!cv) {
        cv = document.createElement("canvas"); cv.style.cssText = "width:100%;height:100%;display:block;touch-action:none;cursor:grab";
        gl = cv.getContext("webgl", {antialias: true}); if (!gl) return false;
        pP = prog(VS_P, FS_P); pM = prog(VS_M, FS_M);
        let arr = null;
        cv.addEventListener("contextmenu", e => e.preventDefault());
        cv.addEventListener("pointerdown", e => { arr = {x: e.clientX, y: e.clientY, b: e.button, sh: e.shiftKey}; cv.setPointerCapture(e.pointerId); });
        cv.addEventListener("pointermove", e => { if (!arr) return; const dx = e.clientX - arr.x, dy = e.clientY - arr.y; arr.x = e.clientX; arr.y = e.clientY;
          if (arr.b === 2 || arr.sh) { const s = cam.d * 0.0016, ct = Math.cos(cam.th), st = Math.sin(cam.th), cp = Math.cos(cam.ph), sp = Math.sin(cam.ph), der = [-st, ct, 0], up = [-sp * ct, -sp * st, cp];
            for (let i = 0; i < 3; i++) cam.t[i] += (-der[i] * dx + up[i] * dy) * s; }
          else { cam.th -= dx * 0.008; cam.ph = Math.max(-1.5, Math.min(1.5, cam.ph + dy * 0.008)); } dibujar(); });
        cv.addEventListener("pointerup", () => { arr = null; });
        cv.addEventListener("wheel", e => { e.preventDefault(); cam.d = Math.max(radio * 0.03, Math.min(radio * 8, cam.d * (e.deltaY > 0 ? 1.12 : 0.89))); dibujar(); }, {passive: false});
        addEventListener("resize", () => dibujar());
      }
      if (cv.parentNode !== contenedor) contenedor.prepend(cv);
      return true;
    }
    function cargarMalla(geo) {
      let tot = 0; geo.elementos.forEach(e => tot += e.v.length);
      const P = new Float32Array(tot), N = new Float32Array(tot); let o = 0; rangos = [];
      geo.elementos.forEach(e => { const v = e.v, ini = o / 3;
        for (let i = 0; i < v.length; i += 9) { const ax = v[i + 3] - v[i], ay = v[i + 4] - v[i + 1], az = v[i + 5] - v[i + 2], bx = v[i + 6] - v[i], by = v[i + 7] - v[i + 1], bz = v[i + 8] - v[i + 2];
          let nx = ay * bz - az * by, ny = az * bx - ax * bz, nz = ax * by - ay * bx; const L = Math.hypot(nx, ny, nz) || 1;
          for (let k = 0; k < 9; k += 3) { P[o] = v[i + k]; P[o + 1] = v[i + k + 1]; P[o + 2] = v[i + k + 2]; N[o] = nx / L; N[o + 1] = ny / L; N[o + 2] = nz / L; o += 3; } }
        rangos.push({id: e.id, ini, n: o / 3 - ini}); });
      bufs.mP = buf(P); bufs.mN = buf(N);
    }
    function cargarNube(ab) {
      n = new Uint32Array(ab, 0, 1)[0];
      const xyz = new Float32Array(ab, 4, n * 3), rgb = new Uint8Array(ab, 4 + 12 * n, n * 3), dist = new Uint8Array(ab, 4 + 15 * n, n), cod = new Uint8Array(ab, 4 + 16 * n, n);
      const cd = new Uint8Array(n * 3), ce = new Uint8Array(n * 3);
      const mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9];
      for (let i = 0; i < n; i++) {
        for (let c = 0; c < 3; c++) { const v = xyz[i * 3 + c]; if (v < mn[c]) mn[c] = v; if (v > mx[c]) mx[c] = v; }
        const d = dist[i]; let r, g, b;
        if (d === 255) { r = 217; g = 50; b = 217; } else if (d <= 4) { r = 22; g = 163; b = 74; } else if (d <= 10) { const t = (d - 4) / 6; r = 22 + t * 223; g = 163 + t * 15; b = 74 - t * 62; } else { const t = Math.min(1, (d - 10) / 40); r = 245 - t * 25; g = 158 - t * 120; b = 11 + t * 27; }
        cd[i * 3] = r; cd[i * 3 + 1] = g; cd[i * 3 + 2] = b;
        const k = COL_EST[cod[i]] || COL_EST[5]; ce[i * 3] = k[0] * 255; ce[i * 3 + 1] = k[1] * 255; ce[i * 3 + 2] = k[2] * 255;
      }
      bufs.p = buf(xyz); bufs.rgb = buf(rgb); bufs.dist = buf(cd); bufs.est = buf(ce);
      cam.t = mn.map((a, i) => (a + mx[i]) / 2); radio = Math.hypot(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]) / 2; cam.d = radio * 1.9; zr = [mn[2], mx[2]];
      return {n, zmin: mn[2], zmax: mx[2]};
    }
    function colores(dron) { colEl = {}; (dron.elementos || []).forEach(f => colEl[f.id] = COL_EST[ESTADOS_ORDEN.indexOf(f.estado)] || COL_EST[4]); }
    function dibujar() {
      if (!cv || !gl) return; const w = cv.clientWidth, h = cv.clientHeight; if (!w || !h) return; const dpr = Math.min(2, devicePixelRatio || 1);
      if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
      gl.viewport(0, 0, cv.width, cv.height); gl.clearColor(0.03, 0.05, 0.09, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT); gl.enable(gl.DEPTH_TEST);
      const e = ojo(), mvp = mul(persp(0.8, cv.width / Math.max(1, cv.height), Math.max(0.05, cam.d - radio * 3), cam.d + radio * 4), mira(e, cam.t));
      if (cfg.nube && n) {
        gl.useProgram(pP); gl.disable(gl.BLEND); gl.depthMask(true);
        gl.uniformMatrix4fv(gl.getUniformLocation(pP, "mvp"), false, mvp); gl.uniform1f(gl.getUniformLocation(pP, "sz"), cfg.tam * dpr); gl.uniform1f(gl.getUniformLocation(pP, "zmax"), cfg.zmax);
        const aP = gl.getAttribLocation(pP, "p"), aC = gl.getAttribLocation(pP, "c");
        gl.bindBuffer(gl.ARRAY_BUFFER, bufs.p); gl.enableVertexAttribArray(aP); gl.vertexAttribPointer(aP, 3, gl.FLOAT, false, 0, 0);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufs[cfg.modo]); gl.enableVertexAttribArray(aC); gl.vertexAttribPointer(aC, 3, gl.UNSIGNED_BYTE, true, 0, 0);
        gl.drawArrays(gl.POINTS, 0, n); gl.disableVertexAttribArray(aC);
      }
      if (cfg.malla && rangos.length) {
        gl.useProgram(pM); gl.uniformMatrix4fv(gl.getUniformLocation(pM, "mvp"), false, mvp); gl.uniform1f(gl.getUniformLocation(pM, "zmax"), cfg.zmax);
        const lz = [e[0] - cam.t[0] + radio, e[1] - cam.t[1] - radio, e[2] - cam.t[2] + radio * 2], L = Math.hypot(...lz); gl.uniform3f(gl.getUniformLocation(pM, "luz"), lz[0] / L, lz[1] / L, lz[2] / L);
        const aP = gl.getAttribLocation(pM, "p"), aN = gl.getAttribLocation(pM, "n");
        gl.bindBuffer(gl.ARRAY_BUFFER, bufs.mP); gl.enableVertexAttribArray(aP); gl.vertexAttribPointer(aP, 3, gl.FLOAT, false, 0, 0);
        gl.bindBuffer(gl.ARRAY_BUFFER, bufs.mN); gl.enableVertexAttribArray(aN); gl.vertexAttribPointer(aN, 3, gl.FLOAT, false, 0, 0);
        gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(!cfg.nube || !n);
        const alfa = cfg.nube && n ? 0.28 : 0.9, uc = gl.getUniformLocation(pM, "col");
        rangos.forEach(r => { const c = colEl[r.id] || COL_EST[4]; gl.uniform4f(uc, c[0], c[1], c[2], alfa); gl.drawArrays(gl.TRIANGLES, r.ini, r.n); });
        gl.disableVertexAttribArray(aN); gl.depthMask(true);
      }
    }
    return {montar, cargarMalla, cargarNube, colores, dibujar, cfg, zr: () => zr, listo: () => n > 0, tieneMalla: () => rangos.length > 0};
  })();
  const ESTADOS_ORDEN = ["construido", "inferido", "dudoso", "no_construido", "no_observable"];
  const LEY = {
    rgb: [["Color real de las fotos", "linear-gradient(90deg,#b8b8b4,#c9a77a,#f2c21a)"]],
    dist: [["≤ 4 cm del modelo", "#16A34A"], ["4–10 cm", "#F5B00B"], ["> 10 cm", "#DC2626"], ["fuera del modelo (> 1 m)", "#D932D9"]],
    est: [["Construido", "#16A34A"], ["Inferido", "#219EB8"], ["Dudoso", "#F59E0B"], ["No construido", "#DC2626"], ["No observable", "#8C99B2"], ["Fuera del modelo", "#D932D9"]]};

  function cerrarNube() { const c = $q("#iaNube"); if (c && c.dataset.abierto) { c.dataset.abierto = ""; c.innerHTML = ""; $q("#iaDronVer").textContent = "Ver la nube de puntos en 3D"; } }
  async function abrirVisorNube() {
    const caja = $q("#iaNube"); if (!caja) return;
    if (caja.dataset.abierto) { caja.dataset.abierto = ""; caja.innerHTML = ""; $q("#iaDronVer").textContent = "Ver la nube de puntos en 3D"; return; }
    caja.dataset.abierto = 1; $q("#iaDronVer").textContent = "Ocultar la nube";
    caja.innerHTML = `<div class="fila" style="margin:10px 0 6px;gap:8px;flex-wrap:wrap;align-items:center">
        <div class="seg" id="iaNubeModo"><button class="on" data-m="rgb">Color real</button><button data-m="dist">Distancia al modelo</button><button data-m="est">Estado del elemento</button></div>
        <label class="nota" style="margin:0"><input type="checkbox" id="iaNubeMalla" checked> modelo BIM</label>
        <label class="nota" style="margin:0"><input type="checkbox" id="iaNubePts" checked> nube</label>
        <label class="nota" style="margin:0">tamaño <input type="range" id="iaNubeTam" min="1" max="6" step="0.5" value="2" style="width:70px"></label>
        <label class="nota" style="margin:0">cortar en altura <input type="range" id="iaNubeZ" min="0" max="1000" value="1000" style="width:120px"> <span id="iaNubeZt"></span></label>
        <span style="flex:1"></span><a class="btn sm" href="/api/ia/escaneo/nube.ply" download>Descargar nube alineada (.ply)</a>${/^sintética/.test(IA.dron.nombre) ? '<a class="btn sm" href="/api/ia/escaneo/simulada.ply" download title="Tal cual saldría de WebODM: sin alinear y, si viene del IFC, en coordenadas UTM">Descargar nube simulada (.ply)</a>' : ""}</div>
      <div id="iaNubeLienzo" style="position:relative;height:560px;border-radius:10px;overflow:hidden;border:1px solid var(--bd)"><div class="vacio" style="position:absolute;inset:0;display:grid;place-items:center">Cargando puntos…</div></div>
      <div class="ia-sem" id="iaNubeLey" style="margin-top:6px;font-size:11.5px"></div>
      <div class="nota">Arrastra para girar · rueda para acercar · clic derecho o Shift para desplazar · el modelo se colorea por el estado que decidió el sistema.</div>`;
    const lienzo = $q("#iaNubeLienzo");
    if (!NUBE.montar(lienzo)) { lienzo.innerHTML = '<div class="vacio">Este navegador no tiene WebGL</div>'; return; }
    try {
      if (!NUBE.tieneMalla()) NUBE.cargarMalla(S.geo || await (await fetch("/api/geometria")).json());
      const r = await fetch("/api/ia/escaneo/nube.bin"); if (!r.ok) throw new Error((await r.json()).error);
      const info = NUBE.cargarNube(await r.arrayBuffer());
      NUBE.colores(IA.dron); lienzo.querySelector(".vacio")?.remove();
      $q("#iaNubeZt").textContent = "todo";
      const ley = () => { $q("#iaNubeLey").innerHTML = LEY[NUBE.cfg.modo === "rgb" ? "rgb" : NUBE.cfg.modo].map(([t, c]) => `<span><i style="display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;background:${c}"></i>${t}</span>`).join("") +
        `<span class="nota">${num(info.n, 0)} puntos mostrados${IA.dron.vista ? ` · ${num(IA.dron.vista.fuera_del_modelo_pct, 1)} % fuera del modelo (grúa, andamio, terreno, vecinos…)` : ""}</span>`; };
      ley();
      caja.querySelectorAll("#iaNubeModo button").forEach(b => b.onclick = () => { caja.querySelectorAll("#iaNubeModo button").forEach(x => x.classList.toggle("on", x === b)); NUBE.cfg.modo = b.dataset.m; ley(); NUBE.dibujar(); });
      $q("#iaNubeMalla").onchange = ev => { NUBE.cfg.malla = ev.target.checked; NUBE.dibujar(); };
      $q("#iaNubePts").onchange = ev => { NUBE.cfg.nube = ev.target.checked; NUBE.dibujar(); };
      $q("#iaNubeTam").oninput = ev => { NUBE.cfg.tam = +ev.target.value; NUBE.dibujar(); };
      $q("#iaNubeZ").oninput = ev => { const [a, b] = NUBE.zr(), v = +ev.target.value; NUBE.cfg.zmax = v >= 1000 ? 1e9 : a + (b - a) * v / 1000;
        $q("#iaNubeZt").textContent = v >= 1000 ? "todo" : `z ≤ ${num(NUBE.cfg.zmax, 1)} m`; NUBE.dibujar(); };
      NUBE.dibujar();
    } catch (err) { lienzo.innerHTML = `<div class="vacio">${e_(err.message)}</div>`; }
  }

  /* ================================================================ enganche con el panel */
  function envolver(nombre, extra) {
    const orig = window[nombre] || eval(nombre);            // las funciones del panel son globales
    const nueva = function () { const r = orig.apply(this, arguments); try { extra(); } catch (err) { console.error("[IA]", err); } return r; };
    try { eval(nombre + " = nueva"); } catch (err) { console.error("[IA] no se pudo enganchar " + nombre, err); }
  }
  envolver("pControl", pintarAuditoria);
  envolver("pParte", () => { pintarParte(); pintarDron(); });
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
