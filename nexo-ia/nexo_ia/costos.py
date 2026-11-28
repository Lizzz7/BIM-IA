"""Costos y presupuesto: el mismo cálculo que el panel NEXO OBRA, más lo que aporta la IA.

Fórmulas del panel (1_Panel/index.html), copiadas para que los números coincidan al céntimo:
  BAC  = r2(Σ r2(metrado × P.U.))                      costo directo del presupuesto
  EV   = Σ cantidad registrada × P.U.                   valorizado (costo directo)
  PV   = Σ monto_cd(actividad) × días laborables hechos / duración     (lunes a sábado, sin feriados)
  SPI  = EV / PV
  Valorización: subtotal = CD + r2(CD·GG) + r2(CD·UT);  bruta = subtotal + r2(subtotal·IGV)

Lo que agrega la IA (todo determinista, con su origen):
  confirmado por dron   registrado en elementos que el último escaneo ve construidos
  en riesgo             registrado en elementos que el dron NO ve (posible valorización sin ejecución)
  por valorizar         visto por el dron y aún sin registrar (propuesta)
  impacto de hallazgos  S/ de los hallazgos del auditor, pendientes y aceptados
  neto recomendado      EV − en riesgo − impacto aceptado
"""
import math
from datetime import date, timedelta

from . import datos as D


def r2(x):
    """Math.round((x + sign(x)·1e-9)·100)/100 del panel (redondeo S10, mitad hacia arriba)."""
    x = float(x or 0)
    return math.floor((x + math.copysign(1e-9, x) if x else 0.0) * 100 + 0.5) / 100


def pie():
    p = D.datos_base().get("pie") or {}
    return {"gg": float(p.get("gg") or 0), "ut": float(p.get("ut") or 0), "igv": float(p.get("igv") or 0)}


def pu(item):
    p = D.partidas().get(item)
    return p["pu"] if p else 0.0


def bac():
    return r2(sum(r2(p["metrado"] * p["pu"]) for p in D.partidas().values()))


def valorizacion(cd):
    """CD -> gastos generales, utilidad, subtotal, IGV y monto bruto (igual que totalVz del panel)."""
    pp, cd = pie(), r2(cd)
    gg, ut = r2(cd * pp["gg"]), r2(cd * pp["ut"])
    sub = r2(cd + gg + ut)
    igv = r2(sub * pp["igv"])
    return {"cd": cd, "gg": gg, "ut": ut, "subtotal": sub, "igv": igv, "bruta": r2(sub + igv),
            "pct": {"gg": pp["gg"], "ut": pp["ut"], "igv": pp["igv"]}}


# ---------------------------------------------------------------- registros (lo valorizado)
def movimientos(reg=None):
    """[(fecha, id_elemento (0 = global), item, cantidad)] de los registros (o de `reg` si se da)."""
    reg = reg if reg is not None else D.leer_registros()
    els = D.elementos()
    out = []
    for k, n in reg.get("elementos", {}).items():
        if int(k) not in els:
            continue
        out += [(f, int(k), it, q) for f, it, q in D.parsear(n.get("registro", ""))]
    out += [(f, 0, it, q) for f, it, q in D.parsear(reg.get("global", ""))]
    return out


def ev(desde="0000", hasta="9999", reg=None):
    return sum(q * pu(it) for f, _, it, q in movimientos(reg) if desde <= f <= hasta)


def ev_por_elemento(hasta="9999", reg=None):
    out = {}
    for f, i, it, q in movimientos(reg):
        if i and f <= hasta:
            out[i] = out.get(i, 0.0) + q * pu(it)
    return out


# ---------------------------------------------------------------- programado (cronograma)
def _crono():
    return D.cronograma()


def _feriados():
    c = _crono()
    return set(c.get("feriados") or (c.get("proyecto", {}).get("calendario", {}) or {}).get("feriados") or [])


def _laborables(a, b, fer):
    if a > b:
        return 0
    d, fin, n = date.fromisoformat(a), date.fromisoformat(b), 0
    while d <= fin:
        if d.weekday() != 6 and d.isoformat() not in fer:
            n += 1
        d += timedelta(days=1)
    return n


def pv(corte):
    """Programado al corte (CD), con el calendario de obra: igual que pvA() del panel."""
    fer = _feriados()
    s = 0.0
    for a in _crono().get("actividades", []):
        hi = min(a["fin"], corte)
        if a["inicio"] <= hi:
            s += a.get("monto_cd", 0) * _laborables(a["inicio"], hi, fer) / max(1, a.get("duracion") or 1)
    return s


def periodo_de(corte):
    for p in _crono().get("periodos", []):
        if p["desde"] <= corte <= p["hasta"]:
            return p
    per = _crono().get("periodos", [])
    return per[-1] if per and corte > per[-1]["hasta"] else (per[0] if per else None)


def corte_defecto():
    """Hoy si cae dentro de la obra; si no, el último día con registros (los datos de prueba son de 2027)."""
    hoy = date.today().isoformat()
    per = _crono().get("periodos", [])
    if per and per[0]["desde"] <= hoy <= per[-1]["hasta"]:
        return hoy
    fechas = [f for f, *_ in movimientos()]
    return max(fechas) if fechas else (per[0]["hasta"] if per else hoy)


# ---------------------------------------------------------------- capítulos
def capitulo(item):
    return item.split(".")[0]


def por_capitulo(corte, reg=None, riesgo_por_item=None):
    caps = {k: v for k, v in (D.datos_base().get("capitulos") or {}).items() if len(k) == 2}
    pres, ej = {}, {}
    for it, p in D.partidas().items():
        pres[capitulo(it)] = pres.get(capitulo(it), 0.0) + p["metrado"] * p["pu"]
    for f, _, it, q in movimientos(reg):
        if f <= corte:
            ej[capitulo(it)] = ej.get(capitulo(it), 0.0) + q * pu(it)
    riesgo = {}
    for it, m in (riesgo_por_item or {}).items():
        riesgo[capitulo(it)] = riesgo.get(capitulo(it), 0.0) + m
    filas = []
    for k in sorted(set(pres) | set(caps), key=lambda x: (len(x), x)):
        pr, e = pres.get(k, 0.0), ej.get(k, 0.0)
        filas.append({"capitulo": k, "nombre": caps.get(k, k), "presupuesto": r2(pr), "valorizado": r2(e),
                      "saldo": r2(pr - e), "avance_pct": round(100 * e / pr, 1) if pr else 0.0,
                      "en_riesgo": r2(riesgo.get(k, 0.0))})
    return filas


# ---------------------------------------------------------------- dron e IA
def dron(escaneo_ultimo, reg=None):
    """Cruce del último escaneo con lo valorizado: confirmado, en riesgo y por valorizar (CD)."""
    if not escaneo_ultimo or escaneo_ultimo.get("vacio"):
        return None
    evel = ev_por_elemento(reg=reg)
    E = D.elementos()
    est = {f["id"]: f["estado"] for f in escaneo_ultimo.get("elementos", [])}
    conf = sum(m for i, m in evel.items() if est.get(i) in ("construido", "inferido"))
    riesgo_ids = {a["id"] for a in escaneo_ultimo.get("alertas_valorizacion", [])}
    riesgo, riesgo_item = 0.0, {}
    reg = reg if reg is not None else D.leer_registros()
    for i in riesgo_ids:
        for _, it, q in D.parsear(reg.get("elementos", {}).get(str(i), {}).get("registro", "")):
            riesgo += q * pu(it)
            riesgo_item[it] = riesgo_item.get(it, 0.0) + q * pu(it)
    sin_ver = sum(m for i, m in evel.items() if est.get(i) in ("no_observable", None) and i not in riesgo_ids)
    return {"fecha": escaneo_ultimo.get("fecha"), "nombre": escaneo_ultimo.get("nombre"),
            "confirmado": r2(conf), "en_riesgo": r2(riesgo), "sin_verificar": r2(sin_ver),
            "por_valorizar": r2(escaneo_ultimo.get("monto_total", 0.0)),
            "por_valorizar_inferido": r2(escaneo_ultimo.get("monto_inferidos", 0.0)),
            "avance_fisico_pct": (escaneo_ultimo.get("avance") or {}).get("total", {}).get("avance_pct"),
            "n_alertas": len(riesgo_ids), "riesgo_por_item": riesgo_item,
            "elementos_en_riesgo": sorted(riesgo_ids)}


def hallazgos_en_soles(auditoria):
    if not auditoria:
        return None
    pend = [h for h in auditoria["hallazgos"] if not h.get("decision") or h["decision"].get("decision") == "pendiente"]
    acep = [h for h in auditoria["hallazgos"] if h.get("decision") and h["decision"].get("decision") == "aceptado"]
    s = lambda L: r2(sum(h.get("impacto_soles") or 0 for h in L))
    # el impacto de D01 (registrado y no visto) ya está en «en riesgo»: no se cuenta dos veces en el neto
    s_sin_dron = lambda L: r2(sum(h.get("impacto_soles") or 0 for h in L if not h["regla"].startswith("D")))
    return {"pendiente": s(pend), "aceptado": s(acep), "aceptado_sin_dron": s_sin_dron(acep),
            "n_pendientes": len(pend), "n_aceptados": len(acep),
            "n_altas_pendientes": sum(h["severidad"] == "alta" for h in pend)}


def resumen(corte=None, reg=None, escaneo_ultimo=None, auditoria=None):
    """Todo lo de costos en un solo objeto (lo usan la tarjeta del panel, el chat, la simulación y el export)."""
    corte = corte or corte_defecto()
    b = bac()
    e_acum, p_acum = ev(hasta=corte, reg=reg), pv(corte)
    per = periodo_de(corte)
    e_mes = ev(per["desde"], min(per["hasta"], corte), reg=reg) if per else 0.0
    dr = dron(escaneo_ultimo, reg=reg)
    ha = hallazgos_en_soles(auditoria)
    riesgo = dr["en_riesgo"] if dr else 0.0
    neto = r2(e_acum - riesgo - (ha["aceptado_sin_dron"] if ha else 0.0))
    spi = round(e_acum / p_acum, 3) if p_acum > 0 else None
    return {
        "corte": corte, "moneda": "S/",
        "presupuesto": {"cd": b, **{k: v for k, v in valorizacion(b).items() if k != "cd"}},
        "programado": r2(p_acum), "valorizado": r2(e_acum), "saldo": r2(b - e_acum),
        "avance_pct": round(100 * e_acum / b, 1) if b else 0.0,
        "programado_pct": round(100 * p_acum / b, 1) if b else 0.0,
        "spi": spi, "estado_plazo": None if spi is None else "a tiempo" if spi >= 1 else "atención" if spi >= 0.9 else "atrasado",
        "periodo": per and {"n": per["n"], "desde": per["desde"], "hasta": per["hasta"], "programado_mes": per.get("pv_mes"),
                            "valorizado_mes": r2(e_mes), "valorizacion_mes": valorizacion(e_mes)},
        "dron": {k: v for k, v in dr.items() if k != "riesgo_por_item"} if dr else None,
        "hallazgos": ha,
        "neto_recomendado": neto, "valorizacion_neta": valorizacion(neto),
        "por_capitulo": por_capitulo(corte, reg=reg, riesgo_por_item=dr["riesgo_por_item"] if dr else None),
        "modelo": {k: v for k, v in desde_modelo().items() if k != "partidas"},
        "cambio_version": cambio_version(),
    }


# ---------------------------------------------------------------- BIM 5D: presupuesto desde el modelo
def desde_modelo():
    """Cuánto del presupuesto sale de elementos del modelo (metrado × P.U.) y cuánto es global (sin elementos)."""
    P = D.partidas()
    del_modelo = {}
    n_el = {}
    for e in D.elementos().values():
        for p in e["partidas"]:
            del_modelo[p["item"]] = del_modelo.get(p["item"], 0.0) + p["metrado"]
            n_el[p["item"]] = n_el.get(p["item"], 0) + 1
    filas, cd_modelo, cd_global = [], 0.0, 0.0
    for it, p in sorted(P.items()):
        monto = p["metrado"] * p["pu"]
        if it in del_modelo:
            cd_modelo += monto
        else:
            cd_global += monto
        filas.append({"item": it, "desc": p["desc"], "und": p["und"], "metrado": p["metrado"], "pu": p["pu"], "monto": r2(monto),
                      "origen": "modelo" if it in del_modelo else "global", "elementos": n_el.get(it, 0),
                      "metrado_elementos": round(del_modelo.get(it, 0.0), 4)})
    total = cd_modelo + cd_global
    return {"cd_modelo": r2(cd_modelo), "cd_global": r2(cd_global), "pct_modelo": round(100 * cd_modelo / total, 1) if total else 0.0,
            "partidas_modelo": sum(f["origen"] == "modelo" for f in filas), "partidas_global": sum(f["origen"] == "global" for f in filas),
            "elementos": len(D.elementos()), "con_apu": len(D.apu() or {}), "partidas": filas}


def cambio_version():
    """Diferencia de presupuesto (CD) entre la versión activa del modelo y la anterior publicada (si hay)."""
    m = D.actual()
    vs = D.registro().get(m.id, {})
    orden = sorted(vs, key=D.clave_version)
    i = orden.index(m.version) if m.version in orden else -1
    if i <= 0:
        return None
    ant = vs[orden[i - 1]]
    pa, pb = ant.partidas, m.partidas
    cambios = []
    for it in sorted(set(pa) | set(pb)):
        a = pa.get(it, {}).get("metrado", 0) * pa.get(it, {}).get("pu", 0)
        b = pb.get(it, {}).get("metrado", 0) * pb.get(it, {}).get("pu", 0)
        if abs(b - a) >= 0.01:
            cambios.append({"item": it, "desc": (pb.get(it) or pa.get(it))["desc"], "antes": r2(a), "despues": r2(b), "diferencia": r2(b - a)})
    cd_a = r2(sum(r2(p["metrado"] * p["pu"]) for p in pa.values()))
    return {"version_anterior": ant.version, "version": m.version, "cd_anterior": cd_a, "cd": bac(), "diferencia": r2(bac() - cd_a),
            "cambios": sorted(cambios, key=lambda c: -abs(c["diferencia"]))[:30]}
