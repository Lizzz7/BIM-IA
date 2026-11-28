"""Simulación paso a paso de la cadena completa, SOLO SIMULACIÓN (no guarda nada):

  1 vuelo del dron ─► 2 nube → elementos ─► 3 elementos → partidas ─► 4 metrado (validado como el complemento)
  ─► 5 S/ (CD → GG, UT → IGV) ─► 6 alertas (dron + auditor con lo nuevo) ─► 7 valorización antes / después

Todo corre en memoria:
  - la nube es sintética (verdad conocida, generada desde el modelo y el cronograma a la fecha de corte),
  - escaneo.procesar(guardar=False): no escribe vista, último escaneo, historial ni bitácora,
  - metrado.aplicar(): registra sobre una COPIA de los registros,
  - auditor y costos leen esa copia con D.simulando(...) y el escaneo simulado con escaneo._ultimo_sim.
"""
import time
from datetime import date as date_

import numpy as np

from nexo_ia import auditor, bitacora, costos, escaneo, metrado, sintetico
from nexo_ia import datos as D
from nexo_ia.ml import NOMBRES_GRUPO


def _partidas_de(registros):
    por = {}
    for r in registros:
        por[r["item"]] = por.get(r["item"], 0.0) + r["cantidad"]
    P = D.partidas()
    caps = D.datos_base().get("capitulos") or {}
    filas = [{"item": i, "desc": P[i]["desc"], "und": P[i]["und"], "cantidad": round(q, 4), "pu": P[i]["pu"],
              "monto": round(q * P[i]["pu"], 2), "capitulo": costos.capitulo(i),
              "subcapitulo": caps.get(i[:5], caps.get(costos.capitulo(i), ""))} for i, q in sorted(por.items()) if i in P]
    cap = {}
    for f in filas:
        c = cap.setdefault(f["capitulo"], {"capitulo": f["capitulo"], "nombre": caps.get(f["capitulo"], f["capitulo"]), "monto": 0.0, "partidas": 0})
        c["monto"] = round(c["monto"] + f["monto"], 2)
        c["partidas"] += 1
    return filas, sorted(cap.values(), key=lambda x: x["capitulo"])


def _con_decisiones(aud):
    dec = bitacora.decisiones()
    aud["hallazgos"] = [dict(h, decision=dec.get(h["id"])) for h in aud["hallazgos"]]
    return aud


def simular(corte=None, semilla=7):
    t0 = time.time()
    corte = corte or costos.corte_defecto()
    reg0 = D.leer_registros()
    ultimo_real = escaneo.ultimo()

    # 1) vuelo: nube sintética como saldría de WebODM (oclusión, ruido, huecos, desalineación)
    nube, verdad, _, rgb = sintetico.generar(corte, semilla=int(semilla), falsos_registrados=2, espaciado=0.10)
    ref = escaneo.referencia()
    cams, _ = escaneo.camaras(ref["P"].min(0), ref["P"].max(0))
    paso1 = {"puntos": int(len(nube)), "puntos_antes_oclusion": verdad["puntos_antes_oclusion"], "camaras": int(len(cams)),
             "plan": "malla nadir 4×4 a 25 m sobre lo más alto + 2 órbitas oblicuas (ver 7_Dron/planificador_dron.py)",
             "ruido_m": verdad["ruido_m"], "huecos": verdad["huecos"],
             "desalineacion_m": round(float(np.linalg.norm(np.array(verdad["T_aplicada"])[:3, 3])), 3),
             "verdad": {"construidos": len(verdad["construidos"]), "retrasados": len(verdad["retrasados"]),
                        "falsos_registrados": verdad["falsos_registrados"]}}

    # 2) nube -> elementos (sin guardar nada)
    r = escaneo.procesar(nube, corte, f"simulación {corte} (semilla {semilla})", verdad=verdad, rgb=rgb, guardar=False)
    paso2 = {"alineacion": {k: r["alineacion"].get(k) for k in ("rmse_m", "traslacion_m", "giro_z_grados", "fraccion_emparejada", "confiable")},
             "conteo": r["avance"]["conteo"], "avance_fisico_pct": r["avance"]["total"]["avance_pct"],
             "concreto_m3": {"total": r["avance"]["total"]["total_m3"], "construido": r["avance"]["total"]["construido_m3"]},
             "por_nivel": r["avance"]["por_nivel"], "exactitud": (r.get("metricas") or {}).get("exactitud"),
             "ids_construidos": r["ids_por_estado"]["construido"], "ids_alerta": [a["id"] for a in r["alertas_valorizacion"]]}

    # 3) elementos -> partidas
    partidas, por_cap = _partidas_de(r["registros"])
    paso3 = {"elementos_nuevos": len({x["id"] for x in r["registros"]}), "grupos": [
        {"nivel": g["nivel"], "grupo": NOMBRES_GRUPO.get(g["grupo"], g["grupo"]), "n_elementos": g["n_elementos"],
         "monto": round(sum(p["monto"] for p in g["partidas"]), 2)} for g in r["resumen"]],
        "partidas": partidas, "por_capitulo": por_cap,
        "inferidos": {"elementos": len({x["id"] for x in r["registros_inferidos"]}), "monto": r["monto_inferidos"],
                      "nota": "Inferidos por secuencia constructiva (no se ven desde el aire): se proponen aparte y no entran al total."}}

    # 4) metrado: mismas validaciones que el complemento, sobre una copia
    reg1, val = metrado.aplicar(reg0, {"fecha": corte, "registros": r["registros"]})
    ej0 = {}
    for _, _, it, q in costos.movimientos(reg0):
        ej0[it] = ej0.get(it, 0.0) + q
    P = D.partidas()
    saldo = [{"item": f["item"], "und": f["und"], "contrato": P[f["item"]]["metrado"], "ejecutado_antes": round(ej0.get(f["item"], 0.0), 4),
              "propuesto": f["cantidad"], "saldo_despues": round(P[f["item"]]["metrado"] - ej0.get(f["item"], 0.0) - f["cantidad"], 4)}
             for f in partidas]
    paso4 = {"valores": len(r["registros"]), "aceptados": len(val["aplicados"]), "rechazados": val["rechazados"][:20],
             "alertas_mayor_metrado": val["alertas"][:20], "saldo_por_partida": saldo, "fecha": corte}

    # 5) S/
    antes = costos.resumen(corte, reg=reg0, escaneo_ultimo=ultimo_real)
    mes_antes = antes["periodo"]["valorizado_mes"] if antes["periodo"] else 0.0
    paso5 = {"propuesta": costos.valorizacion(val["monto_cd"]),
             "mes": {"programado": antes["periodo"] and antes["periodo"]["programado_mes"], "valorizado_antes": mes_antes,
                     "valorizado_despues": costos.r2(mes_antes + val["monto_cd"]),
                     "valorizacion_despues": costos.valorizacion(mes_antes + val["monto_cd"])},
             "periodo": antes["periodo"] and {k: antes["periodo"][k] for k in ("n", "desde", "hasta")}}

    # 6) alertas: dron + auditor como si se hubiera registrado (todo en memoria)
    tok = escaneo._ultimo_sim.set(r)
    try:
        with D.simulando(reg1):
            aud = _con_decisiones(auditor.auditar())
            despues = costos.resumen(corte, reg=reg1, escaneo_ultimo=r, auditoria=aud)
    finally:
        escaneo._ultimo_sim.reset(tok)
    relevantes = [h for h in aud["hallazgos"] if h["regla"] in ("D01", "D02", "R04")]
    paso6 = {"dron": [{"id": a["id"], "texto": a["texto"], "severidad": a["severidad"], "monto": a["monto_registrado"]}
                      for a in r["alertas_valorizacion"]],
             "en_riesgo": despues["dron"]["en_riesgo"] if despues["dron"] else 0.0,
             "sembradas": verdad["falsos_registrados"],
             "detectadas": sorted(set(verdad["falsos_registrados"]) & {a["id"] for a in r["alertas_valorizacion"]}),
             "hallazgos": [{"id": h["id"], "regla": h["regla"], "titulo": h["titulo"], "severidad": h["severidad"],
                            "impacto_soles": h["impacto_soles"], "elementos": h["elementos"][:20]} for h in relevantes][:15],
             "resumen_auditor": aud["resumen"], "impacto_total": aud["impacto_total_soles"]}

    # 7) valorización antes / después
    def corto(c):
        return {"valorizado": c["valorizado"], "programado": c["programado"], "spi": c["spi"], "avance_pct": c["avance_pct"],
                "en_riesgo": c["dron"]["en_riesgo"] if c["dron"] else 0.0, "neto_recomendado": c["neto_recomendado"],
                "valorizacion_neta": c["valorizacion_neta"], "estado_plazo": c["estado_plazo"]}
    paso7 = {"antes": corto(antes), "despues": corto(despues), "por_capitulo": despues["por_capitulo"],
             "presupuesto": despues["presupuesto"],
             "conclusion": _conclusion(antes, despues, val["monto_cd"], paso6)}

    pasos = [
        {"n": 1, "titulo": "Vuelo del dron", "subtitulo": "Nube de puntos simulada", "datos": paso1},
        {"n": 2, "titulo": "Nube → elementos", "subtitulo": "Qué está construido", "datos": paso2},
        {"n": 3, "titulo": "Elementos → partidas", "subtitulo": "Qué partidas del presupuesto avanzan", "datos": paso3},
        {"n": 4, "titulo": "Metrado", "subtitulo": "Validado como el complemento de Revit", "datos": paso4},
        {"n": 5, "titulo": "Soles", "subtitulo": "Costo directo → GG, utilidad → IGV", "datos": paso5},
        {"n": 6, "titulo": "Alertas", "subtitulo": "Lo que no debe valorizarse", "datos": paso6},
        {"n": 7, "titulo": "Valorización", "subtitulo": "Antes y después", "datos": paso7},
    ]
    return {"ok": True, "simulacion": True, "guardado": False, "corte": corte, "semilla": int(semilla),
            "segundos": round(time.time() - t0, 1), "pasos": pasos}


def _conclusion(antes, despues, monto, p6):
    s = f"El dron encontraría S/ {monto:,.2f} de costo directo por valorizar"
    if p6["dron"]:
        s += f" y {len(p6['dron'])} elemento(s) registrados que no se ven (S/ {p6['en_riesgo']:,.2f} en riesgo)"
    s += (f". Valorización neta recomendada al corte: S/ {despues['neto_recomendado']:,.2f} de costo directo "
          f"(S/ {despues['valorizacion_neta']['bruta']:,.2f} con GG, utilidad e IGV).")
    if antes["spi"] is not None and despues["spi"] is not None:
        s += f" SPI {antes['spi']:.2f} → {despues['spi']:.2f}."
    return s


# ---------------------------------------------------------------- la obra construyéndose (nube por etapas)
# Solo en memoria del proceso (nunca a disco): la simulación sigue sin guardar nada.
_nubes = {}


def _dia(fecha, inicio):
    from datetime import datetime
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return (datetime.strptime(fecha, fmt).date() - inicio).days
        except (TypeError, ValueError):
            pass
    return None


def _pv_diario(inicio, dias):
    """Programado acumulado (CD) para cada día desde el inicio: misma fórmula que costos.pv(), con sumas prefijas."""
    from datetime import timedelta
    fer = costos._feriados()
    lab = [0] * (dias + 2)                              # lab[k] = días laborables en [inicio, inicio + k)
    for k in range(dias + 1):
        d = inicio + timedelta(days=k)
        lab[k + 1] = lab[k] + (d.weekday() != 6 and d.isoformat() not in fer)
    idx = lambda f: max(0, min(dias + 1, (date_.fromisoformat(f) - inicio).days))
    pv = [0.0] * (dias + 1)
    for a in D.cronograma().get("actividades", []):
        ini, fin, dur = idx(a["inicio"]), idx(a["fin"]), max(1, a.get("duracion") or 1)
        for k in range(ini, dias + 1):                  # lab(inicio_a, min(fin_a, día))
            pv[k] += a.get("monto_cd", 0) * (lab[min(fin, k) + 1] - lab[ini]) / dur
    return pv


def etapas(corte=None, semilla=7, max_puntos=450_000):
    """La obra construyéndose de principio a fin según el cronograma: nube sintética del edificio COMPLETO (sin oclusión,
    sin desalineación, sin grúa ni material: solo estructura y terreno) y, por punto, el día en que se construye su
    elemento. `corte` es la fecha de la simulación (donde vuela el dron). Devuelve (meta, bytes del visor)."""
    from datetime import timedelta
    from nexo_ia import nube_io
    corte = corte or costos.corte_defecto()
    inicio = date_.fromisoformat(D.datos_base().get("inicio") or D.cronograma()["proyecto"]["inicio"])
    E, Pt = D.elementos(), D.partidas()
    dia_el = {i: _dia(e.get("fecha_prog"), inicio) for i, e in E.items()}
    dia_fin = max([d for d in dia_el.values() if d is not None] + [0])
    fin = (inicio + timedelta(days=dia_fin)).isoformat()
    k = (D.actual().id, D.huellas()["version_datos"], fin, int(semilla))
    if k not in _nubes:
        P, verdad, L, rgb = sintetico.generar(fin, semilla=int(semilla), retrasados=0, falsos_registrados=0, espaciado=0.10,
                                              oclusion=False, desalinear=False, objetos_ajenos=False)
        vox = 0.06
        idx = nube_io.indices_voxel(P, vox)
        while len(idx) > max_puntos:
            vox *= 1.2
            idx = nube_io.indices_voxel(P, vox)
        P, L, rgb = P[idx], L[idx], rgb[idx]
        dia = np.zeros(len(P), np.uint16)
        tipo = np.zeros(len(P), np.uint8)              # 0 = elemento del modelo, 1 = terreno y excavación
        for i in np.unique(L[L >= 0]):
            dia[L == i] = max(0, min(dia_el.get(int(i)) or 0, 65000))
        tipo[L < 0] = 1
        binario = (np.uint32(len(P)).tobytes() + P.astype(np.float32).tobytes() + rgb.astype(np.uint8).tobytes()
                   + dia.tobytes() + tipo.tobytes())
        elementos = sorted([[int(i), int(dia_el[i]), round(sum(p["metrado"] * Pt[p["item"]]["pu"] for p in E[i]["partidas"] if p["item"] in Pt), 2)]
                            for i in set(verdad["construidos"]) if dia_el.get(i) is not None], key=lambda x: x[1])
        pv = _pv_diario(inicio, dia_fin)
        base = {"inicio": inicio.isoformat(), "fin": fin, "dia_fin": dia_fin, "puntos": int(len(P)), "voxel_m": round(vox, 3),
                "elementos": elementos, "programado_semanal": [{"dia": d, "programado": round(pv[d], 2)}
                                                               for d in list(range(0, dia_fin, 7)) + [dia_fin]]}
        if len(_nubes) >= 3:
            _nubes.pop(next(iter(_nubes)))
        _nubes[k] = (base, binario)
    base, binario = _nubes[k]
    meta = {"ok": True, "simulacion": True, "guardado": False, "corte": corte, "semilla": int(semilla),
            "dia_corte": max(0, min((date_.fromisoformat(corte) - inicio).days, base["dia_fin"])), **base,
            "nota": "Edificio según el cronograma, de principio a fin; sin grúa, material ni vecinos. Al corte vuela el dron."}
    return meta, binario
