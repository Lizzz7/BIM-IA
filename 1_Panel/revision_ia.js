/* Revisión inteligente. Sin dependencias de red, HTML no confiable o correcciones automáticas. */
(() => {
  "use strict";
  const R = {tab:"auditoria", caso:"actual", reporte:null, seleccionado:null, comparacion:null,
    escenario:null, versiones:[], estado:null, corte:null, busy:false, run:0};
  const root = () => $("#revisionApp");
  const e = esc, dinero = x => "S/ " + nf(x);
  const post = (ruta, body) => api(ruta, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  const aviso = (texto, error=false) => `<div class="ia-banner ${error ? "ia-error" : ""}">${e(texto)}</div>`;
  function descargar(nombre, objeto){
    const url = URL.createObjectURL(new Blob([JSON.stringify(objeto,null,2)], {type:"application/json"}));
    const a = document.createElement("a"); a.href = url; a.download = nombre; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function tarea(boton, trabajo){
    if(boton) boton.disabled = true;
    const status = $("#iaStatus");
    if(status){ status.textContent = "Procesando…"; status.setAttribute("role","status"); }
    try{ await trabajo(); if($("#iaStatus")) $("#iaStatus").textContent = ""; }
    catch(err){ if($("#iaStatus")) $("#iaStatus").textContent = err.message; else toast(err.message); }
    finally{ if(boton?.isConnected) boton.disabled = false; }
  }
  function pintar(){
    if(!root() || SNAP) return;
    root().innerHTML = `
      <div class="ia-hero"><div><div class="ia-eyebrow">BIM + evidencia + asistencia</div>
        <h1>Revisar antes de aprobar</h1><p>Encuentra diferencias, consulta sus fuentes y prepara una decisión sustentada. Sin modificar automáticamente el presupuesto.</p></div><div class="ia-mark" aria-hidden="true">✧</div></div>
      <div class="ia-tabs" role="tablist" aria-label="Funciones de revisión">${[
        ["auditoria","Auditoría"],["vinculacion","Revisar asignaciones"],["versiones","Comparar versiones"],["escenario","Escenarios APU"]
      ].map(([id,t]) => `<button class="btn" role="tab" data-iatab="${id}" aria-selected="${R.tab === id}">${t}</button>`).join("")}</div>
      <div id="iaProvider" class="nota"></div><div id="iaStatus" class="ia-status" role="status"></div><div id="iaBody"></div>`;
    root().querySelectorAll("[data-iatab]").forEach(b => b.onclick = () => { R.tab = b.dataset.iatab; pintar(); });
    if(S.datos?.modo !== "exportado"){
      $("#iaBody").innerHTML = aviso("Esta sección necesita el servidor independiente: python nexo-ia/servidor.py · http://127.0.0.1:8771/");
      return;
    }
    proveedor();
    if(R.tab === "auditoria") auditoria();
    if(R.tab === "vinculacion") vinculacion();
    if(R.tab === "versiones") versiones();
    if(R.tab === "escenario") escenario();
  }
  async function proveedor(){
    try{
      R.estado ||= await api("/api/estado");
      if(!$("#iaProvider")) return;
      const ia = R.estado.ia;
      $("#iaProvider").textContent = `Motor verificable disponible sin IA. ${ia.llm_configurado ? "LLM configurado: " + ia.modelo : "LLM no configurado."} · ${ia.embeddings_configurados ? "Embeddings configurados: " + ia.modelo_embeddings : "Búsqueda local TF-IDF; no es un modelo de IA."} ${ia.privacidad}`;
    }catch(err){ if($("#iaProvider")) $("#iaProvider").textContent = err.message; }
  }
  function auditoria(){
    $("#iaBody").innerHTML = `<div class="card"><div class="ia-toolbar">
      <label>Datos a revisar<select class="inp" id="iaCaso"><option value="actual">Exportación de la obra · avances de prueba</option><option value="controlado">Caso controlado SIMULADO · no altera registros</option></select></label>
      <button class="btn pri" id="iaAnalizar">Analizar presupuesto</button><button class="btn" id="iaExportar" disabled>Descargar evidencia JSON</button></div>
      <div class="nota">Corte: <b>${e(fmtD(corte()))}</b>. Tolerancia modelo/presupuesto: 3 %. No se evalúan costos reales.</div></div>
      <div id="iaReport"></div>`;
    $("#iaCaso").value = R.caso;
    $("#iaCaso").onchange = ev => { R.caso = ev.target.value; R.reporte = null; R.seleccionado = null; $("#iaReport").innerHTML = ""; $("#iaExportar").disabled = true; };
    $("#iaAnalizar").onclick = ev => analizar(ev.currentTarget);
    $("#iaExportar").onclick = () => descargar(`NEXO_revision_${R.reporte.caso}_${R.reporte.corte}.json`, R.reporte);
    if(R.reporte && (R.caso === "controlado" || R.corte === corte())) pintarReporte();
    else $("#iaReport").innerHTML = `<div class="ia-empty">Ejecuta la revisión. Cada hallazgo conservará su evidencia y sus límites.</div>`;
  }
  async function analizar(boton){
    const caso = R.caso, fecha = corte(), run = ++R.run;
    await tarea(boton, async () => {
      const reporte = await api(`/api/auditoria?caso=${encodeURIComponent(caso)}&corte=${fecha}`);
      if(run !== R.run || R.caso !== caso || R.tab !== "auditoria") return;
      R.reporte = reporte; R.corte = fecha;
      R.seleccionado = R.reporte.hallazgos[0]?.id;
      pintarReporte();
    });
  }
  function pintarReporte(){
    if(!$("#iaReport") || !R.reporte) return;
    const r = R.reporte, c = r.cobertura, s = r.resumen;
    $("#iaExportar").disabled = false;
    $("#iaReport").innerHTML = `${r.caso === "controlado" ? aviso(r.validacion_controlada.aviso + " Resultado del contraste: " + (r.validacion_controlada.coinciden ? "coincide con lo esperado." : "NO coincide; revisar.")) : aviso(R.estado?.aviso || "Datos académicos con avances de prueba y supuestos de presupuesto.")}
      <div class="ia-summary">${[
        ["Hallazgos",s.total,"No equivalen a errores confirmados"],["Inconsistencias",s.inconsistencias,"Incumplen una comprobación definida"],
        ["Advertencias",s.advertencias,"Requieren interpretación humana"],["Excesos por partida",dinero(s.importe_excesos_partida),"Importe por revisar, no ahorro ni pérdida"]
      ].map(([t,v,n]) => `<div class="kpi"><small>${t}</small><b>${e(v)}</b><span>${n}</span></div>`).join("")}</div>
      <details class="card ia-coverage"><summary>Cobertura: ${c.registros_revisados} de ${c.registros_total} registros · ${c.elementos} elementos · corte ${e(fmtD(r.corte))}</summary>
        <p>Excluidos por problemas de datos: ${c.registros_excluidos}. Posteriores al corte: ${c.registros_posteriores_al_corte}. Vínculos con f’c de material comprobado: ${c.vinculos_con_fc_comprobado}.</p>
        <ul>${r.limites.map(l => `<li>${e(l)}</li>`).join("")}</ul></details>
      <div class="ia-columns"><div class="card" style="padding:0"><div class="pad ia-toolbar">
        <label>Filtrar<select class="inp" id="iaFiltro"><option value="">Todos los hallazgos</option><option value="inconsistencia">Inconsistencias</option><option value="advertencia">Advertencias</option><option value="pendientes">Pendientes de revisión</option></select></label></div>
        <div id="iaFindings" class="ia-results"></div></div><div class="card ia-detail" id="iaDetail"></div></div>`;
    $("#iaFiltro").onchange = listaHallazgos;
    listaHallazgos();
  }
  function listaHallazgos(){
    const filtro = $("#iaFiltro").value;
    const hs = R.reporte.hallazgos.filter(h => !filtro || h.nivel === filtro || (filtro === "pendientes" && h.revision.estado === "Pendiente"));
    if(!hs.some(h => h.id === R.seleccionado)) R.seleccionado = hs[0]?.id;
    $("#iaFindings").innerHTML = hs.map(h => `<button class="ia-finding" data-hallazgo="${h.id}" aria-pressed="${h.id === R.seleccionado}">
      <div class="fila"><span class="tag ${h.nivel === "inconsistencia" ? "bad" : "warn"}">${h.nivel === "inconsistencia" ? "Inconsistencia" : "Advertencia"}</span><span class="tag">${e(h.revision.estado)}</span></div>
      <strong>${e(h.titulo)}</strong><small>${e(h.item || "Sin partida")} · ${h.element_ids.length} elementos${h.importe !== null ? " · " + dinero(h.importe) + " por revisar" : ""}</small></button>`).join("") || `<div class="ia-empty">Sin hallazgos para este filtro. No implica ausencia de problemas fuera de la cobertura.</div>`;
    $("#iaFindings").querySelectorAll("[data-hallazgo]").forEach(b => b.onclick = () => { R.seleccionado = b.dataset.hallazgo; listaHallazgos(); });
    detalleHallazgo();
  }
  function detalleHallazgo(){
    const h = R.reporte.hallazgos.find(h => h.id === R.seleccionado);
    const box = $("#iaDetail");
    if(!h){ box.innerHTML = `<div class="ia-empty">Selecciona un hallazgo para examinarlo.</div>`; return; }
    box.innerHTML = `<div class="ia-eyebrow">${e(h.motor)} · ${e(h.id)}</div><h2>${e(h.titulo)}</h2>
      <p>${e(h.detalle)}</p><h3>Propuesta de revisión</h3><p>${e(h.accion)}</p>
      ${h.importe !== null ? aviso("Importe asociado: " + dinero(h.importe) + ". No se suman otra vez los detalles del mismo exceso.") : ""}
      <div class="fila"><button class="btn" id="iaVer3d" ${h.element_ids.length ? "" : "disabled"}>Ver elementos en 3D</button>
      <button class="btn" id="iaExplicar">${R.estado?.ia.llm_configurado ? "Preparar explicación con IA" : "Explicación del motor (sin IA)"}</button></div>
      <div id="iaExplanation"></div><h3 style="margin-top:18px">Evidencia calculada</h3><pre>${e(JSON.stringify(h.evidencia,null,2))}</pre>
      <details><summary>Archivos de referencia</summary><pre>${e(JSON.stringify(R.reporte.fuentes,null,2))}</pre></details>
      <h3 style="margin-top:18px">Decisión del revisor local</h3><p class="nota">Confirmar el hallazgo no modifica cantidades ni aprueba pagos. No hay autenticación multiusuario en este prototipo.</p>
      <textarea class="inp" id="iaMotivo" aria-label="Motivo de revisión" maxlength="2000" placeholder="Indica qué contrastaste y por qué…">${e(h.revision.motivo || "")}</textarea>
      <div class="fila">${["Confirmado","Descartado","Pendiente"].map(t => `<button class="btn" data-revision="${t}" ${LECTURA ? "disabled" : ""}>${t}</button>`).join("")}</div>`;
    const contexto = {hallazgo:h.id, caso:R.reporte.caso, corte:R.reporte.corte};
    $("#iaVer3d").onclick = () => { ir("visor"); resaltar(h.element_ids, (R.caso === "controlado" ? "SIMULADO: " : "") + h.titulo); };
    $("#iaExplicar").onclick = ev => tarea(ev.currentTarget, async () => {
      if(R.estado?.ia.llm_configurado && !await dialogo("<h2>¿Enviar este hallazgo al proveedor de IA?</h2><p>Se enviarán el hallazgo seleccionado y su evidencia. No se envía la geometría ni el archivo completo.</p>", [["Cancelar",false],["Enviar",true,"pri"]])) return;
      const r = await post("/api/explicar",contexto);
      if(R.seleccionado === h.id && $("#iaExplanation")) $("#iaExplanation").innerHTML = aviso(r.advertencia) + `<p>${e(r.texto)}</p><p><b>Revisión propuesta:</b> ${e(r.accion)}</p><small>Cita: ${e(r.citas.join(", "))}</small>`;
    });
    box.querySelectorAll("[data-revision]").forEach(b => b.onclick = () => tarea(b, async () => {
      const r = await post("/api/revision",{...contexto, estado:b.dataset.revision, motivo:$("#iaMotivo").value});
      h.revision = r; listaHallazgos(); toast("Revisión guardada en SQLite; presupuesto sin cambios.");
    }));
  }
  function vinculacion(){
    $("#iaBody").innerHTML = `<div class="card"><h3>Buscar partidas compatibles</h3>
      <p>Solo se utilizan tipo/categoría disponible, familia, material, clase y unidad. No se exige clima, cuadrillas ni horas.</p>
      <div class="ia-toolbar"><label>Elemento<input class="inp" id="iaElemento" type="number" list="iaElementos" value="${e(S.selEl || S.els[0]?.id || "")}"></label>
      <datalist id="iaElementos">${S.els.map(el => `<option value="${el.id}">${e(el.tipo)}</option>`).join("")}</datalist>
      <label>Qué medir<select class="inp" id="iaClase"><option value="concreto">Concreto · m³</option><option value="encofrado">Encofrado · m²</option><option value="acero">Acero · kg</option><option value="ladrillo">Ladrillo · und</option></select></label>
      <label><span>Algoritmo</span><select class="inp" id="iaAlgoritmo"><option value="local">TF-IDF local · sin IA</option><option value="ia">Embeddings de IA · requiere proveedor</option></select></label>
      <button class="btn pri" id="iaSugerir">Proponer candidatas</button></div><div id="iaSuggestions"></div></div>`;
    $("#iaSugerir").onclick = ev => tarea(ev.currentTarget, async () => {
      const usar = $("#iaAlgoritmo").value === "ia";
      if(usar && !await dialogo("<h2>¿Usar embeddings del proveedor?</h2><p>Se enviarán la descripción del elemento y las descripciones de partidas candidatas, no el archivo completo.</p>", [["Cancelar",false],["Enviar",true,"pri"]])) return;
      const r = await post("/api/sugerencias",{element_id:Number($("#iaElemento").value), clase:$("#iaClase").value, usar_ia:usar});
      if(!$("#iaSuggestions")) return;
      $("#iaSuggestions").innerHTML = aviso(r.algoritmo + ". " + r.limite) + `
        <p>Restricciones: unidad <b>${e(r.restricciones.unidad)}</b>; f’c material <b>${e(r.restricciones.fc_material ?? "no disponible")}</b>. Asignaciones actuales: ${e(r.actuales.join(", ") || "ninguna")}.</p>
        ${r.aviso ? aviso(r.aviso) : ""}<div class="ia-scroll"><table class="ia-table"><thead><tr><th>Candidata</th><th>Unidad</th><th class="n">Similitud</th><th class="n">PU</th></tr></thead><tbody>
        ${r.candidatas.map(p => `<tr><td><b>${e(p.item)}</b><small>${e(p.desc)}</small></td><td>${e(p.und)}</td><td class="n">${nf(p.similitud,3)}</td><td class="n">${dinero(p.pu)}</td></tr>`).join("")}</tbody></table></div>
        <p class="nota">Propuestas para contrastar; no se cambia la asignación del modelo ni del presupuesto.</p>`;
    });
  }
  async function cargarVersiones(){
    if(!R.versiones.length) R.versiones = (await api("/api/versiones")).versiones;
  }
  const opciones = seleccion => R.versiones.map(v => `<option value="${e(v.id)}" ${v.id === seleccion ? "selected" : ""}>${e(v.nombre)}</option>`).join("");
  function versiones(){
    $("#iaBody").innerHTML = `<div class="card"><h3>Variaciones verificables entre presupuestos</h3><div id="iaVersionControls">Cargando versiones…</div><div id="iaComparison"></div></div>`;
    tarea(null, async () => {
      await cargarVersiones(); if(!$("#iaVersionControls")) return;
      $("#iaVersionControls").innerHTML = `<div class="ia-toolbar"><label>Base<select class="inp" id="iaBase">${opciones("v3")}</select></label>
        <label>Nueva<select class="inp" id="iaNueva">${opciones("v4")}</select></label><button class="btn pri" id="iaComparar">Comparar y explicar</button></div>
        <p class="nota">Se leen las versiones existentes, sin subir archivos ni editar el presupuesto activo.</p>`;
      $("#iaComparar").onclick = ev => tarea(ev.currentTarget, async () => {
        R.comparacion = await api(`/api/comparacion?a=${encodeURIComponent($("#iaBase").value)}&b=${encodeURIComponent($("#iaNueva").value)}`);
        if($("#iaComparison")) pintarComparacion($("#iaComparison"),R.comparacion);
      });
      if(R.comparacion) pintarComparacion($("#iaComparison"),R.comparacion);
    });
  }
  function pintarComparacion(box,r){
    const t = r.totales, filas = [...r.filas].filter(f => f.tipo !== "Sin cambio").sort((a,b) => Math.abs(b.delta)-Math.abs(a.delta));
    const componentes = [["Cantidad",t.cantidad],["Precio",t.precio],["Altas",t.altas],["Bajas",t.bajas],["Unidades distintas",t.no_comparable],["Redondeo",t.redondeo]];
    box.innerHTML = aviso(`${r.reconciliado ? "Descomposición reconciliada al céntimo." : "ATENCIÓN: no reconciliado."} ${r.limite}`) +
      `<div class="ia-summary">${[["Costo directo base",t.base],["Costo directo nuevo",t.nueva],["Variación",r.delta]].map(([n,v]) => `<div class="kpi"><small>${n}</small><b>${dinero(v)}</b></div>`).join("")}</div>
      <p>Explicación del motor, no de un LLM: ${componentes.filter(([,v]) => v !== 0).map(([n,v]) => `${n.toLowerCase()}: ${dinero(v)}`).join(" · ") || "sin variación monetaria"}.</p>
      <p class="nota">${e(r.metodo)} ${e(r.supuesto || "")}</p><div class="ia-scroll"><table class="ia-table"><thead><tr><th>Partida / fuente</th><th>Tipo</th><th class="n">Q base → nueva</th><th class="n">PU base → nuevo</th><th class="n">Cantidad</th><th class="n">Precio</th><th class="n">Δ costo directo</th></tr></thead><tbody>
      ${filas.map(f => `<tr><td><b>${e(f.item)}</b><small>${e(f.desc)}</small><details><summary>Evidencia</summary><small>${e(f.a?.fuente || "No existía")}<br>${e(f.b?.fuente || "Retirada")}</small></details></td>
      <td>${e(f.tipo)}</td><td class="n">${f.a ? nf(f.a.metrado) + " " + e(f.a.und) : "—"} → ${f.b ? nf(f.b.metrado) + " " + e(f.b.und) : "—"}</td>
      <td class="n">${f.a ? nf(f.a.pu) : "—"} → ${f.b ? nf(f.b.pu) : "—"}</td><td class="n">${dinero(f.cantidad)}</td><td class="n">${dinero(f.precio)}</td><td class="n">${dinero(f.delta)}</td></tr>`).join("") || `<tr><td colspan="7">Sin cambios de importe, descripción o unidad.</td></tr>`}</tbody></table></div>
      <details class="ia-coverage"><summary>Versiones y huellas de origen</summary><pre>${e(JSON.stringify({base:r.a,nueva:r.b},null,2))}</pre></details><button class="btn" data-export-comparison>Descargar comparación JSON</button>`;
    box.querySelector("[data-export-comparison]").onclick = () => descargar("NEXO_comparacion_costos.json",r);
  }
  function escenario(){
    $("#iaBody").innerHTML = `<div class="card"><h3>Escenario de precio de un material</h3>
      <p>No es una predicción. Recalcula el efecto en las partidas que consumen el material mediante el APU existente.</p>
      <div id="iaScenarioControls">Cargando materiales…</div><div id="iaScenario"></div></div>`;
    tarea(null, async () => {
      const r = await api("/api/recursos?version=v4");
      if(!$("#iaScenarioControls")) return;
      $("#iaScenarioControls").innerHTML = `<div class="ia-toolbar"><label style="flex:1">Describe el escenario<input class="inp" id="iaSolicitud" maxlength="600" placeholder="El precio del acero sube 5 %"></label>
        <label>Interpretación<select class="inp" id="iaInterpretacion"><option value="local">Reglas locales · sin IA</option><option value="ia">Modelo de lenguaje IA</option></select></label>
        <button class="btn" id="iaInterpretar">Preparar propuesta</button></div><div id="iaProposal"></div>
        <hr style="border:0;border-top:1px solid var(--bd);margin:16px 0">
        <div class="ia-toolbar"><label>Material · presupuesto v4<select class="inp" id="iaRecurso">${r.recursos.map(p => `<option value="${e(p.codigo)}" ${p.codigo === "0203020003" ? "selected" : ""}>${e(p.desc)} · ${e(p.und)}</option>`).join("")}</select></label>
        <label>Variación del precio %<input class="inp" id="iaPorcentaje" type="number" min="-100" max="100" step="any" value="5"></label>
        <button class="btn pri" id="iaSimular">Confirmar supuesto y simular</button></div>
        <p class="nota">La confirmación crea solo una vista de escenario, nunca cambia el presupuesto ni los registros.</p>`;
      $("#iaInterpretar").onclick = ev => tarea(ev.currentTarget, async () => {
        const usar = $("#iaInterpretacion").value === "ia", texto = $("#iaSolicitud").value;
        if(usar && !await dialogo("<h2>¿Enviar solicitud al proveedor de IA?</h2><p>Se enviarán tu solicitud y las descripciones del catálogo de materiales. Después deberás confirmar los parámetros propuestos.</p>", [["Cancelar",false],["Enviar",true,"pri"]])) return;
        const propuesta = await post("/api/escenario/propuesta",{version:"v4",texto,usar_ia:usar});
        if(!$("#iaProposal")) return;
        $("#iaRecurso").value = propuesta.codigo; $("#iaPorcentaje").value = propuesta.porcentaje;
        $("#iaProposal").innerHTML = aviso(`${propuesta.modo}: ${propuesta.descripcion} · ${propuesta.porcentaje} %. ${propuesta.aviso}`);
      });
      $("#iaSimular").onclick = ev => tarea(ev.currentTarget, async () => {
        const codigo = $("#iaRecurso").value, porcentaje = $("#iaPorcentaje").value, recurso = r.recursos.find(p => p.codigo === codigo);
        if(!await dialogo(`<h2>Confirmar escenario</h2><p>Material: ${e(recurso.desc)}. Variación propuesta: <b>${e(porcentaje)} %</b>.</p><p>Se mantienen cantidades y rendimientos. Solo se calcula costo directo; el original queda intacto.</p>`,[["Cancelar",false],["Simular",true,"pri"]])) return;
        R.escenario = await post("/api/escenario",{version:"v4",codigo,porcentaje});
        if($("#iaScenario")) pintarComparacion($("#iaScenario"),R.escenario);
      });
      if(R.escenario) pintarComparacion($("#iaScenario"),R.escenario);
    });
  }
  window.NexoRevision = {pintar};
  if(S.pag === "revision" && S.datos) pintar();
})();
