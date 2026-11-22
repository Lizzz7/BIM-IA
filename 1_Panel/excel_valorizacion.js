/* ============================================================ EXCEL DE LA VALORIZACIÓN (con fórmulas)
   NEXO OBRA (NO) · se incrusta en el panel con armar_panel.py.
   Solo hojas que salen de datos existentes: presupuesto S10, cronograma, metrados diarios registrados en el panel y los
   datos que el usuario escribió al crear la valorización (cabecera, deducciones, observaciones). Nada se inventa.
   Estilo: azul noche y dorado como el panel. Fórmulas como el modelo de valorización (ROUND a 2 decimales en montos). */
const EXCELJS_URL = "https://cdnjs.cloudflare.com/ajax/libs/exceljs/4.4.0/exceljs.min.js";
function cargarExcelJS(){ return window.ExcelJS ? Promise.resolve() : new Promise((ok, mal) => { const s = document.createElement("script"); s.src = EXCELJS_URL;
  s.onload = ok; s.onerror = () => mal(new Error("No se pudo cargar la librería de Excel (se necesita conexión a internet).")); document.head.appendChild(s); }); }
const COLS = n => { let s = ""; n++; while(n > 0){ const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); } return s; };   // 0 -> A
function curvaPNG(per, pv, ev){
  const W = 900, H = 420, m = {l:80, r:20, t:36, b:50}, cv = document.createElement("canvas"); cv.width = W; cv.height = H; const g = cv.getContext("2d");
  g.fillStyle = "#ffffff"; g.fillRect(0,0,W,H); const max = Math.max(1, ...pv, ...ev.filter(x => x != null));
  const X = i => m.l + (W - m.l - m.r) * (per.length < 2 ? 0 : i / (per.length - 1)), Y = v => H - m.b - (H - m.t - m.b) * v / max;
  g.font = "12px Arial"; g.strokeStyle = "#d6dbe4"; g.fillStyle = "#475569"; g.lineWidth = 1;
  for(let k = 0; k <= 4; k++){ const v = max*k/4; g.beginPath(); g.moveTo(m.l, Y(v)); g.lineTo(W-m.r, Y(v)); g.stroke(); g.textAlign = "right"; g.fillText(nf(v/1000,0) + "k", m.l-8, Y(v)+4); }
  g.textAlign = "center"; per.forEach((p,i) => g.fillText("N° " + String(p.n).padStart(2,"0"), X(i), H - m.b + 18));
  const linea = (arr, col, dash) => { g.strokeStyle = col; g.lineWidth = 3; g.setLineDash(dash ? [8,6] : []); g.beginPath(); let first = true;
    arr.forEach((v,i) => { if(v == null) return; if(first){ g.moveTo(X(i), Y(v)); first = false; } else g.lineTo(X(i), Y(v)); }); g.stroke(); g.setLineDash([]);
    arr.forEach((v,i) => { if(v == null) return; g.fillStyle = col; g.beginPath(); g.arc(X(i), Y(v), 4, 0, 7); g.fill(); }); };
  linea(pv, "#C9973F", true); linea(ev, "#1D4ED8", false);
  g.fillStyle = "#101827"; g.textAlign = "left"; g.font = "bold 14px Arial"; g.fillText("Curva S · costo directo acumulado (S/)", m.l, 22);
  g.font = "12px Arial"; g.fillStyle = "#C9973F"; g.fillText("- - Programado (cronograma)", W - 360, 22); g.fillStyle = "#1D4ED8"; g.fillText("— Valorizado", W - 150, 22);
  return cv.toDataURL("image/png");
}
async function excelValorizacion(v, descargar = true){
  if(!v) return; await cargarExcelJS(); toast("Generando el Excel…");
  const NAVY = "FF101827", NAVY2 = "FF1C2840", GOLD = "FFE5B869", CLARO = "FFF3F5F9", BORDE = "FFB8C2D3", TX = "FF0F172A", MES = "FFFFF7E6", AZUL = "FF1D4ED8";
  const wb = new ExcelJS.Workbook(); wb.creator = "NEXO OBRA (NO)"; wb.calcProperties.fullCalcOnLoad = true;
  const pie = S.datos.pie, cab = v.cab, N2 = '#,##0.00;-#,##0.00;"-"', P4 = '0.00%;-0.00%;"-"', nn = String(v.n).padStart(2,"0");
  const periodoTxt = `del ${fmtD(v.desde)} al ${fmtD(v.hasta)}`, obra = cab.obra || S.datos.modelo + " · casco estructural";
  const fino = {style:"thin", color:{argb:BORDE}}, caja = {top:fino, left:fino, bottom:fino, right:fino};
  const hoja = (nombre, ancho) => { const ws = wb.addWorksheet(nombre, {views:[{showGridLines:false}],
      pageSetup:{paperSize:9, orientation:"landscape", fitToPage:true, fitToWidth:1, fitToHeight:0, margins:{left:0.4, right:0.4, top:0.5, bottom:0.5, header:0.2, footer:0.2}},
      headerFooter:{oddFooter:`&L&8NEXO OBRA (NO) · Valorización N° ${nn}&R&8Página &P de &N`}});
    (ancho || []).forEach((w,i) => ws.getColumn(i+1).width = w); return ws; };
  const titulo = (ws, txt, sub, hasta) => { ws.mergeCells(`A1:${hasta}1`); ws.mergeCells(`A2:${hasta}2`); ws.mergeCells(`A3:${hasta}3`);
    const a = ws.getCell("A1"); a.value = txt; a.font = {name:"Arial", size:14, bold:true, color:{argb:GOLD}}; a.fill = {type:"pattern", pattern:"solid", fgColor:{argb:NAVY}}; a.alignment = {horizontal:"center", vertical:"middle"}; ws.getRow(1).height = 26;
    const b = ws.getCell("A2"); b.value = obra; b.font = {name:"Arial", size:10, bold:true, color:{argb:"FFFFFFFF"}}; b.fill = {type:"pattern", pattern:"solid", fgColor:{argb:NAVY2}}; b.alignment = {horizontal:"center"};
    const c = ws.getCell("A3"); c.value = sub; c.font = {name:"Arial", size:9, color:{argb:"FF475569"}}; c.alignment = {horizontal:"center", wrapText:true}; ws.getRow(3).height = 24; };
  const enc = (ws, fila, textos, desde = 1) => textos.forEach((t,i) => { const c = ws.getCell(fila, desde + i); c.value = t; c.font = {name:"Arial", size:9, bold:true, color:{argb:GOLD}};
    c.fill = {type:"pattern", pattern:"solid", fgColor:{argb:NAVY}}; c.alignment = {horizontal:"center", vertical:"middle", wrapText:true}; c.border = caja; });
  const celda = (ws, ref, valor, fmt, extra = {}) => { const c = ws.getCell(ref); c.value = valor; c.font = {name:"Arial", size:9, color:{argb:TX}, ...(extra.font||{})};
    if(fmt) c.numFmt = fmt; c.border = caja; if(extra.fill) c.fill = {type:"pattern", pattern:"solid", fgColor:{argb:extra.fill}}; if(extra.al) c.alignment = extra.al; return c; };
  const nota = (ws, ref, txt) => { const c = ws.getCell(ref); c.value = txt; c.font = {name:"Arial", size:8, italic:true, color:{argb:"FF64748B"}}; };
  const oscuro = {font:{bold:true, color:{argb:GOLD}}, fill:NAVY};

  // hojas en el orden del informe
  const wc = hoja("CARATULA", [4, 30, 62, 4]), wi = hoja("CONTENIDO", [6, 34, 80]);
  const wm = hoja("D.01 RESUMEN METRADOS", [11, 50, 6, 12, 12, 12, 12, 9, 12, 9]), wd = hoja("D.01 METRADOS DIARIOS");
  const wr = hoja("D.02 RESUMEN VALORIZACION", [36, 16, 15, 9, 15, 9, 15, 9, 15, 9]);
  const wv = hoja("D.02 VALORIZACION MENSUAL", [11, 46, 6, 11, 10, 13, 11, 13, 8, 11, 13, 8, 11, 13, 8, 11, 13, 8]);
  const ws = hoja("D.02 CURVA S", [8, 40, 15, 9, 15, 9, 15, 9, 15, 9]), wp = hoja("D.03 PROGRAMADO VS EJECUTADO");
  const VQ = "'D.02 VALORIZACION MENSUAL'", DQ = "'D.01 METRADOS DIARIOS'", RQ = "'D.02 RESUMEN VALORIZACION'";

  const filas = [...Object.entries(S.datos.capitulos).map(([it, d]) => ({it, d, cap:true})), ...S.partidas.map(x => ({it:x.item, x}))]
    .filter(f => !f.cap || S.partidas.some(x => x.item.startsWith(f.it + "."))).sort((a,b) => a.it.localeCompare(b.it, "es", {numeric:true}));
  const ant = v.ant, act = v.act;

  // ---------- METRADOS DIARIOS
  const dias = []; for(let d = dISO(v.desde); isoD(d) <= v.hasta; d.setDate(d.getDate()+1)) dias.push(isoD(d));
  [11, 46, 6, 11, ...dias.map(() => 6.4), 12].forEach((w,i) => wd.getColumn(i+1).width = w);
  const lTot = COLS(4 + dias.length), lUlt = COLS(3 + dias.length);
  titulo(wd, "METRADOS DIARIOS DEL MES", `Valorización N° ${nn} · ${periodoTxt} · registrados en el panel NEXO OBRA`, lTot);
  enc(wd, 5, ["Ítem", "Descripción de partida", "Und.", "Metrado contrato", ...dias.map(d => +d.slice(8)), "TOTAL MES"]);
  enc(wd, 6, ["", "", "", "", ...dias.map(d => ["D","L","M","M","J","V","S"][dISO(d).getDay()]), ""]);
  const porDia = {}; v.det.forEach(r => { const k = r.it + "|" + r.f; porDia[k] = (porDia[k]||0) + r.q; });
  const filaDiario = {}; let r = 7;
  filas.forEach(f => {
    if(f.cap){ celda(wd, `A${r}`, f.it, null, {font:{bold:true}, fill:CLARO}); wd.mergeCells(`B${r}:${lTot}${r}`); celda(wd, `B${r}`, f.d, null, {font:{bold:true}, fill:CLARO}); r++; return; }
    const x = f.x; celda(wd, `A${r}`, x.item); celda(wd, `B${r}`, x.desc, null, {al:{wrapText:true, vertical:"middle"}}); celda(wd, `C${r}`, x.und, null, {al:{horizontal:"center"}}); celda(wd, `D${r}`, x.metrado, N2);
    dias.forEach((d,i) => { const q = porDia[x.item + "|" + d]; celda(wd, `${COLS(4+i)}${r}`, q ? Math.round(q*10000)/10000 : null, N2, laborable(d) ? {} : {fill:"FFE5E7EB"}); });
    celda(wd, `${lTot}${r}`, {formula:`ROUND(SUM(E${r}:${lUlt}${r}),2)`}, N2, {font:{bold:true}, fill:MES});
    filaDiario[x.item] = r; r++; });
  nota(wd, `B${r+1}`, "Gris = domingo o feriado del calendario de obra. Cantidades tal como se registraron en el panel (sin redondear); el total del mes se redondea a 2 decimales.");
  wd.views = [{state:"frozen", xSplit:4, ySplit:6, showGridLines:false}];

  // ---------- VALORIZACIÓN MENSUAL
  titulo(wv, `VALORIZACIÓN DEL MES DE ${mesTxt(v.desde).toUpperCase()}`, `Valorización N° ${nn} · ${periodoTxt} · contratista: ${cab.empresa || "—"} · residente: ${cab.residente || "—"} · supervisor: ${cab.supervisor || "—"}`, "R");
  ["A5:A6","B5:B6","C5:C6","D5:F5","G5:I5","J5:L5","M5:O5","P5:R5"].forEach(m => wv.mergeCells(m));
  enc(wv, 5, ["Partida", "Descripción", "Und."]); ["D","G","J","M","P"].forEach((c,i) => enc(wv, 5, [["PRESUPUESTO","ANTERIOR","ACTUAL","ACUMULADO","SALDO"][i]], wv.getColumn(c).number));
  enc(wv, 6, ["Metrado","P.U. S/","Presup. S/","Metrado","Valoriz. S/","%","Metrado","Valoriz. S/","%","Metrado","Valoriz. S/","%","Metrado","Valoriz. S/","%"], 4);
  const filaVal = {}, capFilas = []; r = 7;
  filas.forEach(f => {
    if(f.cap){ capFilas.push({r, it:f.it}); celda(wv, `A${r}`, f.it, null, {font:{bold:true}, fill:CLARO}); celda(wv, `B${r}`, f.d, null, {font:{bold:true}, fill:CLARO});
      ["C","D","E","G","J","M","P"].forEach(c => celda(wv, `${c}${r}`, null, null, {fill:CLARO})); r++; return; }
    const x = f.x; filaVal[x.item] = r;
    celda(wv, `A${r}`, x.item); celda(wv, `B${r}`, x.desc, null, {al:{wrapText:true, vertical:"middle"}}); celda(wv, `C${r}`, x.und, null, {al:{horizontal:"center"}});
    celda(wv, `D${r}`, x.metrado, N2); celda(wv, `E${r}`, x.pu, N2); celda(wv, `F${r}`, {formula:`ROUND(D${r}*E${r},2)`}, N2);
    celda(wv, `G${r}`, r2(ant[x.item]||0), N2); celda(wv, `H${r}`, {formula:`ROUND(G${r}*E${r},2)`}, N2); celda(wv, `I${r}`, {formula:`IF(F${r}=0,0,ROUND(H${r}/F${r},4))`}, P4);
    celda(wv, `J${r}`, {formula:`${DQ}!${lTot}${filaDiario[x.item]}`}, N2, {fill:MES}); celda(wv, `K${r}`, {formula:`ROUND(J${r}*E${r},2)`}, N2, {fill:MES}); celda(wv, `L${r}`, {formula:`IF(F${r}=0,0,ROUND(K${r}/F${r},4))`}, P4, {fill:MES});
    celda(wv, `M${r}`, {formula:`G${r}+J${r}`}, N2); celda(wv, `N${r}`, {formula:`H${r}+K${r}`}, N2); celda(wv, `O${r}`, {formula:`IF(F${r}=0,0,ROUND(N${r}/F${r},4))`}, P4);
    celda(wv, `P${r}`, {formula:`D${r}-M${r}`}, N2); celda(wv, `Q${r}`, {formula:`F${r}-N${r}`}, N2); celda(wv, `R${r}`, {formula:`IF(F${r}=0,0,ROUND(Q${r}/F${r},4))`}, P4);
    r++; });
  capFilas.forEach(({r:rc, it}) => { const hijos = S.partidas.filter(x => x.item.startsWith(it + ".")).map(x => filaVal[x.item]);
    ["F","H","K","N","Q"].forEach(c => celda(wv, `${c}${rc}`, {formula:`ROUND(${hijos.map(h => `${c}${h}`).join("+")},2)`}, N2, {font:{bold:true}, fill:CLARO}));
    ["I","L","O","R"].forEach((c,i) => celda(wv, `${c}${rc}`, {formula:`IF(F${rc}=0,0,ROUND(${["H","K","N","Q"][i]}${rc}/F${rc},4))`}, P4, {font:{bold:true}, fill:CLARO})); });
  const hojas = Object.values(filaVal);
  r++; const rCD = r, rGG = r+1, rUT = r+2, rST = r+3, rIGV = r+4, rTOT = r+5;
  const pct = (rr, lbl, val) => { celda(wv, `B${rr}`, lbl, null, {font:{bold:true}}); celda(wv, `C${rr}`, val, P4, {font:{bold:true, color:{argb:AZUL}}}); };
  celda(wv, `B${rCD}`, "COSTO DIRECTO", null, oscuro); celda(wv, `C${rCD}`, null, null, {fill:NAVY}); pct(rGG, "GASTOS GENERALES (% del CD)", pie.gg||0); pct(rUT, "UTILIDAD (% del CD)", pie.ut||0);
  celda(wv, `B${rST}`, "SUBTOTAL", null, {font:{bold:true}, fill:CLARO}); celda(wv, `C${rST}`, null, null, {fill:CLARO}); pct(rIGV, "IGV (% del subtotal)", pie.igv||0); celda(wv, `B${rTOT}`, "TOTAL", null, oscuro); celda(wv, `C${rTOT}`, null, null, {fill:NAVY});
  ["F","H","K","N","Q"].forEach(c => {
    celda(wv, `${c}${rCD}`, {formula:`ROUND(${hojas.map(h => `${c}${h}`).join("+")},2)`}, N2, oscuro);
    celda(wv, `${c}${rGG}`, {formula:`ROUND(${c}${rCD}*$C$${rGG},2)`}, N2); celda(wv, `${c}${rUT}`, {formula:`ROUND(${c}${rCD}*$C$${rUT},2)`}, N2);
    celda(wv, `${c}${rST}`, {formula:`${c}${rCD}+${c}${rGG}+${c}${rUT}`}, N2, {font:{bold:true}, fill:CLARO}); celda(wv, `${c}${rIGV}`, {formula:`ROUND(${c}${rST}*$C$${rIGV},2)`}, N2);
    celda(wv, `${c}${rTOT}`, {formula:`${c}${rST}+${c}${rIGV}`}, N2, oscuro); });
  ["I","L","O","R"].forEach((c,i) => [rCD, rTOT].forEach(rr => celda(wv, `${c}${rr}`, {formula:`IF(F${rr}=0,0,ROUND(${["H","K","N","Q"][i]}${rr}/F${rr},4))`}, P4, oscuro)));
  nota(wv, `B${rTOT+2}`, "Montos: ROUND(metrado × P.U.; 2) como en S10. El metrado del mes viene de la hoja «D.01 METRADOS DIARIOS». Porcentajes en azul: del presupuesto S10.");
  wv.views = [{state:"frozen", xSplit:3, ySplit:6, showGridLines:false}];

  // ---------- RESUMEN DE VALORIZACIÓN
  titulo(wr, "RESUMEN DE VALORIZACIÓN DE OBRA - MENSUAL", `Valorización N° ${nn} · ${periodoTxt} · emitida el ${fmtD(v.emision)}`, "J");
  ["C5:D5","E5:F5","G5:H5","I5:J5"].forEach(m => wr.mergeCells(m));
  enc(wr, 5, ["CONCEPTO", "PRESUPUESTO"]); ["C","E","G","I"].forEach((c,i) => enc(wr, 5, [["ANTERIOR","DEL MES","ACUMULADO","SALDO"][i]], wr.getColumn(c).number));
  enc(wr, 6, ["", "S/", "S/", "%", "S/", "%", "S/", "%", "S/", "%"]);
  [["COSTO DIRECTO", rCD], ["GASTOS GENERALES", rGG], ["UTILIDAD", rUT], ["SUBTOTAL", rST], ["IGV", rIGV]].forEach(([lbl, rv], i) => { const rr = 7 + i;
    celda(wr, `A${rr}`, lbl, null, {font:{bold:true}, fill:CLARO});
    [["B","F"],["C","H"],["E","K"],["G","N"],["I","Q"]].forEach(([c, src]) => celda(wr, `${c}${rr}`, {formula:`${VQ}!${src}${rv}`}, N2));
    ["D","F","H","J"].forEach((c,j) => celda(wr, `${c}${rr}`, {formula:`IF($B${rr}=0,0,ROUND(${["C","E","G","I"][j]}${rr}/$B${rr},4))`}, P4)); });
  celda(wr, "A12", "TOTAL (VALORIZACIÓN BRUTA)", null, oscuro);
  ["B","C","E","G","I"].forEach(c => celda(wr, `${c}12`, {formula:`${c}10+${c}11`}, N2, oscuro));
  ["D","F","H","J"].forEach((c,j) => celda(wr, `${c}12`, {formula:`IF($B12=0,0,ROUND(${["C","E","G","I"][j]}12/$B12,4))`}, P4, oscuro));
  wr.mergeCells("A15:E15"); celda(wr, "A15", "DEDUCCIONES DEL MES (escritas al crear la valorización)", null, oscuro);
  celda(wr, "A16", "Valorización bruta del mes"); celda(wr, "D16", null); celda(wr, "E16", {formula:"E12"}, N2, {font:{bold:true}});
  celda(wr, "A17", "(-) Amortización de adelanto directo"); celda(wr, "D17", (parseFloat(v.ded.adel)||0)/100, P4, {font:{color:{argb:AZUL}}}); celda(wr, "E17", {formula:"-ROUND(E16*D17,2)"}, N2);
  celda(wr, "A18", "(-) Amortización de adelanto de materiales (S/)"); celda(wr, "D18", parseFloat(v.ded.mat)||0, N2, {font:{color:{argb:AZUL}}}); celda(wr, "E18", {formula:"-ROUND(D18,2)"}, N2);
  celda(wr, "A19", "(-) Retención por fondo de garantía"); celda(wr, "D19", (parseFloat(v.ded.ret)||0)/100, P4, {font:{color:{argb:AZUL}}}); celda(wr, "E19", {formula:"-ROUND(E16*D19,2)"}, N2);
  celda(wr, "A20", "NETO A PAGAR", null, oscuro); celda(wr, "D20", null, null, {fill:NAVY}); celda(wr, "E20", {formula:"SUM(E16:E19)"}, N2, oscuro);
  for(let rr = 16; rr <= 20; rr++) ["B","C"].forEach(c => { if(!wr.getCell(c+rr).value) celda(wr, c+rr, null, null, rr === 20 ? {fill:NAVY} : {}); });
  nota(wr, "A21", "Valores en azul: los escribiste al crear la valorización. Puedes cambiarlos aquí y todo se recalcula.");
  let rf = 25; if(v.obs){ celda(wr, "A23", "Observaciones", null, {font:{bold:true}}); wr.mergeCells("A24:J26"); celda(wr, "A24", v.obs, null, {al:{wrapText:true, vertical:"top"}}); rf = 30; }
  [["B", "Residente de obra", cab.residente], ["E", "Supervisión", cab.supervisor], ["H", "Propietario", cab.propietario]].forEach(([c, t, n]) => {
    const k = wr.getCell(`${c}${rf}`); k.value = `${t}\n${n || ""}`; k.alignment = {horizontal:"center", wrapText:true}; k.font = {name:"Arial", size:9}; k.border = {top:{style:"thin", color:{argb:"FF0F172A"}}}; });
  wr.getRow(rf).height = 30;

  // ---------- RESUMEN DE METRADOS
  titulo(wm, "RESUMEN DE METRADOS DEL MES", `Valorización N° ${nn} · ${periodoTxt}`, "J");
  enc(wm, 5, ["Ítem", "Descripción de partida", "Und.", "Exp. técnico", "Acum. anterior", "Mes actual", "Total acumulado", "% acum.", "Saldo", "Saldo %"]);
  r = 6; filas.forEach(f => { if(f.cap){ celda(wm, `A${r}`, f.it, null, {font:{bold:true}, fill:CLARO}); wm.mergeCells(`B${r}:J${r}`); celda(wm, `B${r}`, f.d, null, {font:{bold:true}, fill:CLARO}); r++; return; }
    const x = f.x, s = filaVal[x.item]; celda(wm, `A${r}`, x.item); celda(wm, `B${r}`, x.desc, null, {al:{wrapText:true, vertical:"middle"}}); celda(wm, `C${r}`, x.und, null, {al:{horizontal:"center"}});
    [["D","D"],["E","G"],["F","J"],["G","M"]].forEach(([c, src]) => celda(wm, `${c}${r}`, {formula:`${VQ}!${src}${s}`}, N2, c === "F" ? {fill:MES} : {}));
    celda(wm, `H${r}`, {formula:`IF(D${r}=0,0,ROUND(G${r}/D${r},4))`}, P4); celda(wm, `I${r}`, {formula:`D${r}-G${r}`}, N2); celda(wm, `J${r}`, {formula:`IF(D${r}=0,0,ROUND(I${r}/D${r},4))`}, P4); r++; });
  wm.views = [{state:"frozen", ySplit:5, showGridLines:false}];

  // ---------- CURVA S
  const per = periodos(), regs = todos();
  const evMes = p => r2(regs.filter(x => x.f >= p.desde && x.f <= p.hasta).reduce((s,x) => s + r2(x.q*pu(x.it)), 0));
  titulo(ws, 'CONTROL DE OBRA · CURVA "S"', `Programado: cronograma de obra · Valorizado: metrados registrados en el panel (N° ${nn} desde la hoja de valorización)`, "J");
  celda(ws, "B4", "Costo directo contratado (S/)", null, {font:{bold:true}, fill:CLARO}); celda(ws, "C4", {formula:`${VQ}!F${rCD}`}, N2, {font:{bold:true}});
  ws.mergeCells("C5:F5"); ws.mergeCells("G5:J5"); enc(ws, 5, ["N°", "Periodo", "PROGRAMADO (CD)"]); enc(ws, 5, ["VALORIZADO (CD)"], 7);
  enc(ws, 6, ["", "", "Mes S/", "%", "Acum. S/", "% acum.", "Mes S/", "%", "Acum. S/", "% acum."]);
  const pvArr = [], evArr = []; let pa = 0, ea = 0;
  per.forEach((p, i) => { const rr = 7 + i, pvm = CRONO?.periodos.find(x => x.n === p.n)?.pv_mes || 0, esta = p.n === v.n, fut = p.n > v.n, op = esta ? {fill:MES} : {};
    celda(ws, `A${rr}`, p.n, null, {al:{horizontal:"center"}, ...op}); celda(ws, `B${rr}`, `${mesTxt(p.desde)} (${fmtD(p.desde)} al ${fmtD(p.hasta)})`, null, op);
    celda(ws, `C${rr}`, pvm, N2); celda(ws, `D${rr}`, {formula:`IF($C$4=0,0,ROUND(C${rr}/$C$4,4))`}, P4); celda(ws, `E${rr}`, {formula: i ? `E${rr-1}+C${rr}` : `C${rr}`}, N2); celda(ws, `F${rr}`, {formula:`IF($C$4=0,0,ROUND(E${rr}/$C$4,4))`}, P4);
    if(fut) ["G","H","I","J"].forEach(c => celda(ws, `${c}${rr}`, null));
    else { celda(ws, `G${rr}`, esta ? {formula:`${VQ}!K${rCD}`} : evMes(p), N2, op); celda(ws, `H${rr}`, {formula:`IF($C$4=0,0,ROUND(G${rr}/$C$4,4))`}, P4);
      celda(ws, `I${rr}`, {formula: i ? `I${rr-1}+G${rr}` : `G${rr}`}, N2); celda(ws, `J${rr}`, {formula:`IF($C$4=0,0,ROUND(I${rr}/$C$4,4))`}, P4); }
    pa += pvm; pvArr.push(pa);
    if(fut) evArr.push(null); else { ea += esta ? Object.entries(act).reduce((s,[it,q]) => s + r2(r2(q)*pu(it)), 0) : evMes(p); evArr.push(ea); } });
  nota(ws, `B${8 + per.length}`, "Meses anteriores: metrados registrados actualmente en el panel. Mes de esta valorización: enlazado a la hoja de valorización.");
  ws.addImage(wb.addImage({base64:curvaPNG(per, pvArr, evArr), extension:"png"}), {tl:{col:0, row:9 + per.length}, ext:{width:900, height:420}});

  // ---------- PROGRAMADO VS EJECUTADO
  const perPE = per.filter(p => p.n <= v.n), lastC = COLS(5 + perPE.length * 2);
  [11, 44, 6, 11, 10, 13, ...perPE.flatMap(() => [12, 12])].forEach((w,i) => wp.getColumn(i+1).width = w);
  titulo(wp, "COMPARACIÓN DE PROGRAMADO VS EJECUTADO (S/)", `Hasta la valorización N° ${nn} · programado: cronograma · ejecutado: metrados registrados en el panel`, lastC);
  ["A5:A6","B5:B6","C5:C6","D5:D6","E5:E6","F5:F6"].forEach(m => wp.mergeCells(m));
  enc(wp, 5, ["Ítem", "Descripción", "Und.", "Metrado", "P.U. S/", "Parcial S/"]);
  perPE.forEach((p,i) => { const c0 = 7 + i*2; wp.mergeCells(5, c0, 5, c0+1); enc(wp, 5, [`${mesTxt(p.desde)} · N° ${String(p.n).padStart(2,"0")}`], c0); enc(wp, 6, ["PROGRAMADO", "EJECUTADO"], c0); });
  const progP = (item, p) => CRONO ? r2(CRONO.actividades.reduce((s,a) => { const q = a.partidas.find(x => x.item === item); return q ? s + q.metrado * fracAct(a, p.desde, p.hasta) : s; }, 0) * pu(item)) : 0;
  const ejeP = (item, p) => p.n === v.n ? null : r2(r2(regs.filter(x => x.it === item && x.f >= p.desde && x.f <= p.hasta).reduce((s,x) => s + x.q, 0)) * pu(item));
  r = 7; const leaf = [];
  filas.forEach(f => { if(f.cap){ celda(wp, `A${r}`, f.it, null, {font:{bold:true}, fill:CLARO}); wp.mergeCells(`B${r}:${lastC}${r}`); celda(wp, `B${r}`, f.d, null, {font:{bold:true}, fill:CLARO}); r++; return; }
    const x = f.x; leaf.push(r); celda(wp, `A${r}`, x.item); celda(wp, `B${r}`, x.desc, null, {al:{wrapText:true, vertical:"middle"}}); celda(wp, `C${r}`, x.und, null, {al:{horizontal:"center"}});
    celda(wp, `D${r}`, x.metrado, N2); celda(wp, `E${r}`, x.pu, N2); celda(wp, `F${r}`, {formula:`ROUND(D${r}*E${r},2)`}, N2);
    perPE.forEach((p,i) => { const c0 = 7 + i*2; celda(wp, `${COLS(c0-1)}${r}`, progP(x.item, p), N2);
      const e = ejeP(x.item, p); celda(wp, `${COLS(c0)}${r}`, e == null ? {formula:`${VQ}!K${filaVal[x.item]}`} : e, N2, p.n === v.n ? {fill:MES} : {}); }); r++; });
  celda(wp, `B${r}`, "TOTAL COSTO DIRECTO", null, oscuro); ["A","C","D","E"].forEach(c => celda(wp, `${c}${r}`, null, null, {fill:NAVY}));
  for(let c = 5; c <= 5 + perPE.length*2; c++){ const L = COLS(c); celda(wp, `${L}${r}`, {formula:`ROUND(${leaf.map(h => `${L}${h}`).join("+")},2)`}, N2, oscuro); }
  wp.views = [{state:"frozen", xSplit:3, ySplit:6, showGridLines:false}];

  // ---------- CONTENIDO y CARÁTULA (al final, ya con las filas conocidas)
  titulo(wi, "CONTENIDO DE LA VALORIZACIÓN", `Valorización N° ${nn} · ${periodoTxt}`, "C"); enc(wi, 5, ["N°", "Hoja", "Contenido"]);
  [["D.01 RESUMEN METRADOS", "Metrado contratado, anterior, del mes, acumulado y saldo por partida"], ["D.01 METRADOS DIARIOS", "Metrados registrados en el panel, día por día"],
   ["D.02 RESUMEN VALORIZACION", "Costo directo, gastos generales, utilidad, IGV, deducciones y neto a pagar"], ["D.02 VALORIZACION MENSUAL", "Valorización por partida: presupuesto, anterior, actual, acumulado y saldo"],
   ["D.02 CURVA S", "Programado (cronograma) vs valorizado, mes a mes"], ["D.03 PROGRAMADO VS EJECUTADO", "Monto programado y ejecutado por partida y por mes"]].forEach(([h, d], i) => {
    celda(wi, `A${6+i}`, i+1, null, {al:{horizontal:"center"}}); celda(wi, `B${6+i}`, {text:h, hyperlink:`#'${h}'!A1`}, null, {font:{color:{argb:AZUL}, underline:true}}); celda(wi, `C${6+i}`, d); });
  nota(wi, "B13", "No se incluyen hojas cuyos datos no existen en el panel (personal, manifiesto de gastos, almacén, panel fotográfico, cuaderno de obra).");

  wc.mergeCells("B3:C3"); celda(wc, "B3", "INFORME DE VALORIZACIÓN MENSUAL DE OBRA", null, {font:{size:18, bold:true, color:{argb:GOLD}}, fill:NAVY, al:{horizontal:"center", vertical:"middle"}}); wc.getRow(3).height = 42;
  wc.mergeCells("B4:C4"); celda(wc, "B4", `VALORIZACIÓN N° ${nn} · ${mesTxt(v.desde).toUpperCase()}`, null, {font:{size:13, bold:true, color:{argb:"FFFFFFFF"}}, fill:NAVY2, al:{horizontal:"center", vertical:"middle"}}); wc.getRow(4).height = 26;
  const car = [["Obra", obra], ["Periodo", periodoTxt], ["Contratista", cab.empresa || "—"], ["Propietario", cab.propietario || "—"], ["Ubicación", cab.ubicacion || "—"],
    ["Residente de obra", cab.residente || "—"], ["Supervisor", cab.supervisor || "—"], ["Fecha de emisión", fmtD(v.emision)], ["Inicio de obra", fmtD(S.datos.inicio)]];
  car.forEach(([k, x], i) => { celda(wc, `B${6+i}`, k, null, {font:{bold:true}, fill:CLARO}); celda(wc, `C${6+i}`, x, null, {al:{wrapText:true}}); });
  const rp = 6 + car.length;
  [["Presupuesto total (con IGV)", `${RQ}!B12`, '"S/ "#,##0.00'], ["Valorización bruta del mes", `${RQ}!E12`, '"S/ "#,##0.00'], ["Neto a pagar", `${RQ}!E20`, '"S/ "#,##0.00'],
   ["Avance acumulado (costo directo)", `${RQ}!H7`, P4]].forEach(([k, f, fmt], i) => { celda(wc, `B${rp+i}`, k, null, {font:{bold:true}, fill:CLARO}); celda(wc, `C${rp+i}`, {formula:f}, fmt, {font:{bold:true}}); });
  const logo = ls("logo"); if(logo && /^data:image\/(png|jpeg)/.test(logo)) wc.addImage(wb.addImage({base64:logo, extension:logo.includes("png") ? "png" : "jpeg"}), {tl:{col:1, row:rp+5}, ext:{width:180, height:80}});
  nota(wc, `B${rp+11}`, "Generado con NEXO OBRA (NO) a partir del presupuesto, el cronograma y los metrados diarios registrados en el panel.");

  const buf = await wb.xlsx.writeBuffer(); S._ultimoExcel = buf;
  if(descargar){ const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([buf], {type:"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}));
    a.download = `Valorizacion_N${nn}_${v.desde.slice(0,7)}_${S.datos.modelo}.xlsx`; a.click(); toast("Excel generado."); }
  return buf;
}
