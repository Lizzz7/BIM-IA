/* Casos útiles del APU: cotización con fuente y explicación de variaciones. Sin porcentajes protagonistas. */
(() => {
  "use strict";
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"]/g,c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const sol = n => "S/ " + Number(n).toLocaleString("es-PE",{minimumFractionDigits:2,maximumFractionDigits:2});
  // El registro manual del panel conserva su API; solo incorpora identidad de reintento.
  const apiPanel = window.api, pendientes = new Map();
  if(apiPanel) window.api = async function(ruta, opciones){
    let clave, op=opciones;
    if(ruta==="/api/metrado" && opciones?.body){
      const body=JSON.parse(opciones.body);
      if(!body.simular){
        clave=opciones.body;if(!pendientes.has(clave))pendientes.set(clave,crypto.randomUUID());
        op={...opciones,body:JSON.stringify({...body,request_id:pendientes.get(clave)})};
      }
    }
    const r=await apiPanel(ruta,op);if(clave)pendientes.delete(clave);return r;
  };
  async function api(ruta, datos){
    const r = await fetch(ruta,datos ? {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(datos)} : {});
    const d = await r.json(); if(!r.ok || d.ok === false) throw Error(d.error || "Solicitud no válida"); return d;
  }
  function descargar(datos){
    const u = URL.createObjectURL(new Blob([JSON.stringify(datos,null,2)],{type:"application/json"}));
    const a = document.createElement("a");a.href=u;a.download="NEXO_revision_presupuesto.json";a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);
  }
  async function accion(b, trabajo){
    b.disabled=true;
    try{ await trabajo(); }catch(err){ if($("#apuMensaje")) $("#apuMensaje").textContent=err.message; }
    finally{ b.disabled=false; }
  }
  function resultado(box,r){
    box.innerHTML=`<div class="ia-caja"><b>${r.reconciliado ? "Comparación reconciliada al céntimo" : "Revisar reconciliación"}</b>
      <p>Base: ${sol(r.totales.base)} · Propuesta/nueva: ${sol(r.totales.nueva)} · Diferencia: <b>${sol(r.delta)}</b></p>
      <p class="nota">${esc(r.metodo)} ${esc(r.limite)} ${esc(r.supuesto || "")}</p>
      <div style="overflow:auto"><table><thead><tr><th>Partida</th><th>Cantidad</th><th>Precio</th><th>Δ CD</th></tr></thead><tbody>${r.filas.filter(f=>f.tipo!=="Sin cambio").map(f=>
        `<tr><td>${esc(f.item)} · ${esc(f.desc)}<div class="nota">${esc(f.tipo)}</div></td><td>${sol(f.cantidad)}</td><td>${sol(f.precio)}</td><td>${sol(f.delta)}</td></tr>`).join("") || '<tr><td colspan="4">Sin cambios</td></tr>'}</tbody></table></div>
      <details><summary>Fuentes, recursos APU y componentes no explicados</summary><pre style="white-space:pre-wrap;max-height:320px;overflow:auto">${esc(JSON.stringify({base:r.a,nueva:r.b,cotizacion:r.cotizacion,explicacion:r.explicacion_apu || r.cambios_apu},null,2))}</pre></details>
      <button class="btn sm" data-export>Descargar evidencia JSON</button></div>`;
    box.querySelector("[data-export]").onclick=()=>descargar(r);
  }
  async function montar(){
    if($("#apuRevision")) return;
    const pag=$("#pag-valorizaciones");if(!pag)return;
    const box=document.createElement("section");box.id="apuRevision";box.className="card";box.style.marginBottom="14px";
    box.innerHTML=`<h3>Cotizaciones y variaciones del presupuesto</h3><p class="nota">Revisiones propuestas: no modifican el presupuesto vigente ni documentos cerrados. No son ahorros comprobados.</p>
      <div id="apuMensaje" role="status"></div><details><summary>Actualizar una cotización documentada</summary>
      <div class="fila"><label>Material <select class="inp" id="apuRecurso"></select></label><label>Precio cotizado <input class="inp" id="apuPrecio" type="number" min="0" step="any"></label>
      <label>Unidad <input class="inp" id="apuUnidad" style="width:70px"></label><label>Fecha <input class="inp" id="apuFecha" type="date"></label></div>
      <div class="fila"><label><input id="apuIGV" type="checkbox"> Incluye IGV</label><label>Tasa IGV (fracción) <input class="inp" id="apuTasa" type="number" min="0" max="1" step="any" value="0.18" style="width:80px"></label>
      <label>Fuente <input class="inp" id="apuFuente" maxlength="1000" placeholder="Cotización / proveedor / documento"></label></div>
      <div class="fila"><label style="flex:1">Alcance comparable (entrega, transporte, especificación)<input class="inp" id="apuAlcance" maxlength="2000" style="width:100%"></label>
      <button class="btn pri" id="apuProponer">Revisar efecto en partidas</button></div><div id="apuPropuesta"></div><button class="btn" id="apuConfirmar" hidden>Guardar revisión propuesta (no aprobar)</button></details>
      <details style="margin-top:14px"><summary>Comparar versiones y explicar recursos APU</summary><div class="fila">
      <label>Base <select class="inp" id="apuBase"></select></label><label>Nueva <select class="inp" id="apuNueva"></select></label><button class="btn" id="apuComparar">Comparar</button></div><div id="apuComparacion"></div></details>`;
    pag.prepend(box);
    try{
      const [cat,rec]=await Promise.all([api("/api/presupuestos"),api("/api/presupuestos/recursos")]);
      if(!box.isConnected)return;
      for(const sel of ["#apuBase","#apuNueva"]) $(sel).innerHTML=cat.versiones.map(v=>`<option value="${esc(v.id)}">${esc(v.nombre)}</option>`).join("");
      if(cat.versiones.some(v=>v.id==="v3"))$("#apuBase").value="v3";
      $("#apuNueva").value="actual";
      $("#apuRecurso").innerHTML=rec.recursos.map(r=>`<option value="${esc(r.codigo)}">${esc(r.desc)}</option>`).join("");
      function recurso(){const r=rec.recursos.find(r=>r.codigo===$("#apuRecurso").value);if(r){$("#apuUnidad").value=r.und;$("#apuPrecio").value=r.precio;}}
      $("#apuRecurso").onchange=recurso;recurso();
      $("#apuFecha").value=new Date().toISOString().slice(0,10);
      let propuesta=null;
      const pedido=()=>({version:"actual",codigo:$("#apuRecurso").value,precio:$("#apuPrecio").value,unidad:$("#apuUnidad").value,
        fuente:$("#apuFuente").value,fecha:$("#apuFecha").value,incluye_igv:$("#apuIGV").checked,tasa_igv:$("#apuTasa").value,
        alcance:$("#apuAlcance").value,moneda:"PEN"});
      box.addEventListener("input",()=>{propuesta=null;$("#apuConfirmar").hidden=true;});
      $("#apuProponer").onclick=ev=>accion(ev.currentTarget,async()=>{
        const p=pedido(),r=await api("/api/presupuestos/cotizar",p);resultado($("#apuPropuesta"),r);
        propuesta=p;$("#apuConfirmar").hidden=false;$("#apuMensaje").textContent="Propuesta calculada; pendiente de confirmación.";
      });
      $("#apuConfirmar").onclick=ev=>accion(ev.currentTarget,async()=>{
        if(!propuesta)return;
        if(!confirm("¿Guardar esta revisión como propuesta? No actualizará el presupuesto vigente ni aprobará pagos."))return;
        const r=await api("/api/presupuestos/cotizar/confirmar",propuesta);$("#apuMensaje").textContent=r.aviso+" ID: "+r.id;
      });
      $("#apuComparar").onclick=ev=>accion(ev.currentTarget,async()=>{
        resultado($("#apuComparacion"),await api(`/api/presupuestos/comparar?a=${encodeURIComponent($("#apuBase").value)}&b=${encodeURIComponent($("#apuNueva").value)}`));
      });
    }catch(err){$("#apuMensaje").textContent=err.message;}
  }
  const original=pValorizaciones;
  pValorizaciones=function(){const r=original.apply(this,arguments);montar();return r;};
  if(typeof S!=="undefined" && S.pag==="valorizaciones")montar();
})();
