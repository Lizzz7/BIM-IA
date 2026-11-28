"""Export para Power BI: un .zip con CSV en esquema estrella + guía de relaciones y medidas DAX.

CSV en UTF-8 con BOM (Excel y Power BI detectan los acentos), separador coma y punto decimal.
En Power BI: Obtener datos › Carpeta (o Texto/CSV) › cada archivo; tipos: fecha en «fecha», decimal en montos.
"""
import csv
import io
import json
import zipfile
from datetime import datetime

from . import bitacora, costos, escaneo
from . import datos as D

LEEME = """# NEXO OBRA · datos para Power BI ({obra} {version}, datos v.{vdatos}, generado {fecha})

Esquema estrella (montos en S/, costo directo salvo que diga otra cosa):

| Tabla | Clave | Contenido |
|---|---|---|
| dim_partidas | item | presupuesto: capítulo, descripción, unidad, metrado de contrato, P.U., monto CD, origen (modelo/global) |
| dim_elementos | elemento_id | elementos del modelo de Revit: tipo, grupo, nivel, paquete, sector, actividad, fecha programada |
| dim_periodos | n | periodos de valorización: programado del mes y acumulado (cronograma) |
| dim_parametros | — | GG, utilidad, IGV del pie de presupuesto |
| fact_registros | — | metrado ejecutado: fecha, elemento_id (0 = partida global), item, cantidad, monto_cd |
| fact_hallazgos | hallazgo_id | auditoría IA: regla, método, severidad, impacto S/, decisión humana |
| fact_hallazgo_elemento | — | puente hallazgo ↔ elemento |
| fact_dron_elementos | elemento_id | último escaneo: estado (construido, inferido, dudoso, no_construido, no_observable), cobertura, S/ registrado |
| fact_escaneos | — | historial de escaneos: fecha, avance físico %, S/ propuesto, S/ en riesgo |

Relaciones (uno a muchos):
- dim_partidas[item] → fact_registros[item]
- dim_elementos[elemento_id] → fact_registros[elemento_id], fact_dron_elementos[elemento_id], fact_hallazgo_elemento[elemento_id]
- fact_hallazgos[hallazgo_id] → fact_hallazgo_elemento[hallazgo_id]
- Tabla de fechas (CALENDAR) → fact_registros[fecha]; dim_periodos para la curva S.

Medidas DAX sugeridas:
```
Presupuesto CD = SUM(dim_partidas[monto_cd])
Valorizado CD = SUM(fact_registros[monto_cd])
Programado CD = MAX(dim_periodos[pv_acum])            -- con filtro de periodo
SPI = DIVIDE([Valorizado CD], [Programado CD])
GG = ROUND([Valorizado CD] * MAX(dim_parametros[gg]), 2)
Utilidad = ROUND([Valorizado CD] * MAX(dim_parametros[ut]), 2)
Subtotal = [Valorizado CD] + [GG] + [Utilidad]
Valorización bruta = [Subtotal] + ROUND([Subtotal] * MAX(dim_parametros[igv]), 2)
En riesgo (dron) = CALCULATE(SUM(fact_dron_elementos[monto_registrado]), fact_dron_elementos[alerta] = 1)
Impacto hallazgos pendientes = CALCULATE(SUM(fact_hallazgos[impacto_soles]), fact_hallazgos[decision] = "pendiente")
```
Totales de control al generar: presupuesto CD = {bac}, valorizado CD = {ev}.
"""


def _csv(filas, columnas):
    b = io.StringIO()
    w = csv.writer(b, lineterminator="\n")
    w.writerow(columnas)
    for f in filas:
        w.writerow(["" if f.get(c) is None else f.get(c) for c in columnas])
    return ("﻿" + b.getvalue()).encode("utf-8")


def tablas(auditoria=None):
    P, E = D.partidas(), D.elementos()
    caps = D.datos_base().get("capitulos") or {}
    mod = {f["item"]: f for f in costos.desde_modelo()["partidas"]}
    t = {}
    t["dim_partidas"] = (_csv([{"item": i, "capitulo": costos.capitulo(i), "capitulo_nombre": caps.get(costos.capitulo(i), ""),
                                "subcapitulo": caps.get(i[:5], ""), "descripcion": p["desc"], "und": p["und"], "metrado": p["metrado"],
                                "pu": p["pu"], "monto_cd": costos.r2(p["metrado"] * p["pu"]), "origen": mod[i]["origen"],
                                "n_elementos": mod[i]["elementos"]} for i, p in sorted(P.items())],
                              ["item", "capitulo", "capitulo_nombre", "subcapitulo", "descripcion", "und", "metrado", "pu", "monto_cd", "origen", "n_elementos"]))
    t["dim_elementos"] = _csv([{"elemento_id": i, "tipo": e["tipo"], "grupo": e["grupo"], "nivel": e["nivel"], "paquete": e["paquete"],
                                "sector": e["sector"], "actividad": e.get("actividad"), "fecha_prog": _iso(e.get("fecha_prog")),
                                "monto_cd": costos.r2(sum(p["metrado"] * P[p["item"]]["pu"] for p in e["partidas"] if p["item"] in P))}
                               for i, e in sorted(E.items())],
                              ["elemento_id", "tipo", "grupo", "nivel", "paquete", "sector", "actividad", "fecha_prog", "monto_cd"])
    t["dim_periodos"] = _csv(D.cronograma().get("periodos", []), ["n", "desde", "hasta", "pv_mes", "pv_acum"])
    pp = costos.pie()
    t["dim_parametros"] = _csv([{"gg": pp["gg"], "ut": pp["ut"], "igv": pp["igv"], "moneda": "PEN", "obra": D.actual().id,
                                 "version": D.actual().version, "version_datos": D.huellas()["version_datos"]}],
                               ["gg", "ut", "igv", "moneda", "obra", "version", "version_datos"])
    t["fact_registros"] = _csv([{"fecha": f, "elemento_id": i, "item": it, "cantidad": q, "monto_cd": round(q * costos.pu(it), 6),
                                 "origen": "elemento" if i else "global"} for f, i, it, q in costos.movimientos()],
                               ["fecha", "elemento_id", "item", "cantidad", "monto_cd", "origen"])
    hall = (auditoria or {}).get("hallazgos", [])
    t["fact_hallazgos"] = _csv([{"hallazgo_id": h["id"], "regla": h["regla"], "nombre": h["nombre"], "metodo": h["metodo"],
                                 "severidad": h["severidad"], "titulo": h["titulo"], "impacto_soles": h["impacto_soles"],
                                 "confianza": h["confianza"], "partidas": " ".join(h["partidas"]), "n_elementos": len(h["elementos"]),
                                 "decision": (h.get("decision") or {}).get("decision", "pendiente"),
                                 "decidido_por": (h.get("decision") or {}).get("usuario")} for h in hall],
                               ["hallazgo_id", "regla", "nombre", "metodo", "severidad", "titulo", "impacto_soles", "confianza",
                                "partidas", "n_elementos", "decision", "decidido_por"])
    t["fact_hallazgo_elemento"] = _csv([{"hallazgo_id": h["id"], "elemento_id": e} for h in hall for e in h["elementos"]],
                                       ["hallazgo_id", "elemento_id"])
    u = escaneo.ultimo()
    evel = costos.ev_por_elemento()
    alerta = {a["id"] for a in (u or {}).get("alertas_valorizacion", [])}
    t["fact_dron_elementos"] = _csv([{"fecha_escaneo": u["fecha"], "elemento_id": f["id"], "estado": f["estado"],
                                      "cobertura_visible": f["cobertura_visible"], "visible": f["visible"], "concreto_m3": f["concreto_m3"],
                                      "registrado": int(bool(f.get("registrado"))), "monto_registrado": round(evel.get(f["id"], 0.0), 2),
                                      "alerta": int(f["id"] in alerta)} for f in (u or {}).get("elementos", [])],
                                    ["fecha_escaneo", "elemento_id", "estado", "cobertura_visible", "visible", "concreto_m3",
                                     "registrado", "monto_registrado", "alerta"])
    t["fact_escaneos"] = _csv([{"fecha": h["fecha"], "nombre": h["nombre"], "procesado": h["procesado"],
                                "avance_fisico_pct": h["avance"]["total"]["avance_pct"], "monto_propuesto": h["monto_propuesto"],
                                "monto_en_riesgo": round(sum(a["monto_registrado"] for a in h["alertas"]), 2), "n_alertas": len(h["alertas"])}
                               for h in escaneo.historial()],
                              ["fecha", "nombre", "procesado", "avance_fisico_pct", "monto_propuesto", "monto_en_riesgo", "n_alertas"])
    return t


def _iso(f):
    if not f:
        return None
    try:
        return datetime.strptime(f, "%d/%m/%Y").date().isoformat()
    except ValueError:
        return f


def zip_powerbi(auditoria=None) -> bytes:
    m = D.actual()
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for nombre, datos in tablas(auditoria).items():
            z.writestr(f"{nombre}.csv", datos)
        z.writestr("LEEME_PowerBI.md", LEEME.format(obra=m.id, version=m.version, vdatos=D.huellas()["version_datos"],
                                                     fecha=datetime.now().strftime("%Y-%m-%d %H:%M"),
                                                     bac=f"{costos.bac():,.2f}", ev=f"{costos.ev():,.2f}"))
        z.writestr("costos_resumen.json", json.dumps(costos.resumen(auditoria=auditoria, escaneo_ultimo=escaneo.ultimo()),
                                                     ensure_ascii=False, indent=1, default=str))
    if not D.en_simulacion():
        bitacora.anotar("export_powerbi", presupuesto_cd=costos.bac(), valorizado_cd=round(costos.ev(), 2))
    return b.getvalue()
