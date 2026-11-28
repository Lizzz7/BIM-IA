"""Auditor previo al cierre de la valorización.

Capa 1 (este módulo): reglas DETERMINISTAS. Cada hallazgo lleva su evidencia: archivo de origen,
fórmula, valores usados y la versión de datos. Ningún número de aquí lo produce un LLM.
Capa 2 (ml.py): modelos estadísticos / de ML que proponen hallazgos adicionales con su confianza.
Capa 3 (narrador.py): el LLM solo redacta la observación técnica y se verifica contra la evidencia.
"""
import hashlib
import re
from collections import defaultdict

from . import datos as D

SEV = {"alta": 0, "media": 1, "baja": 2}


def _fc(txt):
    m = re.findall(r"f'?c\s*=?\s*(\d{3})", txt or "", re.I)
    return int(m[0]) if m else None


def _pu_concreto(eid):
    """(item, P.U.) de la partida de concreto del elemento, o (None, None)."""
    e = D.elementos().get(eid)
    if not e:
        return None, None
    for p in e["partidas"]:
        if p["clase"] == "concreto":
            return p["item"], D.partidas()[p["item"]]["pu"]
    return None, None


def hallazgo(regla, nombre, metodo, severidad, titulo, elementos, evidencia, impacto=None, partidas=None, confianza=None, clave=""):
    # ID estable entre recálculos (no depende de cantidades) y único: decisiones Aceptar/Descartar se guardan con él
    base = f"{regla}|{','.join(map(str, sorted(elementos)))}|{','.join(sorted(partidas or []))}|{clave}"
    return {
        "id": f"{regla}-{elementos[0] if elementos else 0}-{hashlib.sha1(base.encode()).hexdigest()[:6]}",
        "regla": regla, "nombre": nombre, "metodo": metodo, "severidad": severidad, "titulo": titulo,
        "elementos": elementos, "partidas": partidas or [], "impacto_soles": None if impacto is None else round(impacto, 2),
        "confianza": confianza, "evidencia": evidencia,
    }


# ---------------------------------------------------------------- reglas
def r01_solapes():
    """Volumen de concreto contado dos veces: dos sólidos que se intersectan sin estar unidos en Revit."""
    out = []
    for s in D.auditoria_modelo()["solapes"]:
        if s.get("unidos"):
            continue
        a, b, v = s["a"], s["b"], s["volumen_m3"]
        ia, pa = _pu_concreto(a)
        ib, pb = _pu_concreto(b)
        if pa is None and pb is None:
            continue
        pus = [x for x in (pa, pb) if x is not None]
        pu = min(pus)
        ta, tb = (D.elementos().get(x, {}).get("tipo", "?") for x in (a, b))
        out.append(hallazgo(
            "R01", "Solape de concreto sin unir", "determinista", "media" if v * pu >= 20 else "baja",
            f"{ta} se cruza con {tb}: {v:.3f} m³ contados dos veces",
            [a, b], partidas=[x for x in (ia, ib) if x], impacto=v * pu,
            evidencia={"fuente": "auditoria_*.json › solapes (geometría de Revit)",
                       "formula": "impacto = volumen_solape × min(P.U. concreto de ambos)  [estimación conservadora]",
                       "valores": {"volumen_m3": v, "pu_a": pa, "pu_b": pb, "item_a": ia, "item_b": ib, "unidos": False}}))
    return out


def r02_fc_tipo_vs_material():
    """El nombre del tipo dice un f'c y el material estructural otro: el presupuesto usa el material."""
    out = []
    for eid, m in D.metrados_modelo().items():
        if eid not in D.elementos():
            continue
        ft = _fc(m["tipo"])
        fm = sorted({_fc(x["material"]) for x in m["materiales"]} - {None})
        if ft and fm and ft not in fm:
            item, pu = _pu_concreto(eid)
            alt = next((x for x in D.partidas().values() if item and x["item"][:5] == item[:5] and x["item"] != item
                        and x["desc"].upper().startswith("CONCRETO") and _fc(x["desc"]) == ft), None)
            dif = (alt["pu"] - pu) * m["volumen_m3"] if alt and pu else None
            out.append(hallazgo(
                "R02", "f'c del tipo distinto al del material", "determinista", "alta",
                f"{m['tipo']}: el tipo indica f'c={ft} pero el material es f'c={fm[0]}",
                [eid], partidas=[item] + ([alt["item"]] if alt else []) if item else [], impacto=dif,
                evidencia={"fuente": "metrados_*.json › tipo, materiales; presupuesto › P.U.",
                           "formula": "f'c(nombre del tipo) ≠ f'c(material estructural); impacto si fuera el f'c del tipo = (P.U. alternativo − P.U. presupuestado) × volumen",
                           "valores": {"fc_tipo": ft, "fc_material": fm, "volumen_m3": m["volumen_m3"], "item_presupuestado": item, "pu": pu,
                                       "item_alternativo": alt["item"] if alt else None, "pu_alternativo": alt["pu"] if alt else None}}))
    return out


def r03_sin_material():
    out = []
    for eid, m in D.metrados_modelo().items():
        e = D.elementos().get(eid)
        if e and not m["materiales"]:
            out.append(hallazgo(
                "R03", "Elemento presupuestado sin material", "determinista", "media",
                f"{m['tipo']} ({m['categoria']}) no tiene material asignado en Revit",
                [eid], partidas=[p["item"] for p in e["partidas"]],
                evidencia={"fuente": "metrados_*.json › materiales = []",
                           "formula": "elemento con partidas en el presupuesto y sin material estructural",
                           "valores": {"categoria": m["categoria"], "volumen_m3": m["volumen_m3"], "fc_asumido": 280}}))
    return out


def r04_mayor_metrado():
    """Mayor metrado real vs. falsa alarma por sumar fracciones diarias en coma flotante.

    El complemento compara acumulado > contrato × (1 + 1e-6): al registrar un elemento en varios días
    (p. ej. 2.839/7 por día) la suma puede quedar en 2.8390000001 y dispara una alerta que no es real.
    Tolerancia de medición usada aquí: 0.1 % del metrado del elemento y al menos 0.001 unidades.
    """
    out = []
    ej = D.ejecutado_por_elemento()
    obs = {int(k): v.get("obs", "") for k, v in D.leer_registros()["elementos"].items()}
    for eid, acc in ej.items():
        e = D.elementos().get(eid)
        if not e:
            continue
        for p in e["partidas"]:
            q, c = acc.get(p["item"], 0.0), p["metrado"]
            exceso, tol = q - c, max(0.001 * c, 0.001)
            if exceso > tol:
                pu = D.partidas()[p["item"]]["pu"]
                out.append(hallazgo(
                    "R04", "Mayor metrado registrado", "determinista", "alta",
                    f"{e['tipo']}: {p['item']} acumulado {q:.3f} > contrato {c:.3f}",
                    [eid], partidas=[p["item"]], impacto=exceso * pu,
                    evidencia={"fuente": "registros.json + metrado del elemento",
                               "formula": "impacto = (acumulado − contrato) × P.U.  si exceso > max(0.1 %·contrato, 0.001)",
                               "valores": {"acumulado": round(q, 6), "contrato": c, "pu": pu, "tolerancia": tol}}))
            elif exceso > 0 and p["item"] in obs.get(eid, ""):
                out.append(hallazgo(
                    "R04b", "Falsa alarma de mayor metrado (redondeo)", "determinista", "baja",
                    f"{e['tipo']}: la alerta de {p['item']} es por coma flotante (exceso {exceso:.2e}), no es mayor metrado",
                    [eid], partidas=[p["item"]],
                    evidencia={"fuente": "registros.json › obs (alerta guardada por el complemento)",
                               "formula": "0 < acumulado − contrato ≤ tolerancia de medición",
                               "valores": {"acumulado": repr(q), "contrato": c, "exceso": exceso, "tolerancia": tol,
                                           "obs_guardada": obs.get(eid, "")}}))
    return out


def r05_secuencia():
    """Actividad con avance registrado antes de que sus predecesoras tengan avance (tren de trabajo)."""
    acts = {a["id"]: a for a in D.cronograma()["actividades"]}
    ape = D.actividades_por_elemento()
    primera, elems_act = {}, defaultdict(set)
    for eid, n in D.leer_registros()["elementos"].items():
        eid = int(eid)
        e = D.elementos().get(eid)
        if not e:
            continue
        clase = {p["item"]: p["clase"] for p in e["partidas"]}
        for f, it, q in D.parsear(n.get("registro", "")):
            act = ape.get(eid, {}).get(clase.get(it))
            if act and q > 0:
                primera[act] = min(primera.get(act, f), f)
                elems_act[act].add(eid)
    con_elementos = {a for v in ape.values() for a in v.values()}
    out = []
    for act, f in primera.items():
        for pre in acts.get(act, {}).get("predecesoras", []):
            if pre in con_elementos and not (pre in primera and primera[pre] <= f):
                out.append(hallazgo(
                    "R05", "Secuencia constructiva no respetada", "determinista", "alta",
                    f"«{acts[act]['nombre']}» tiene avance desde {f} pero «{acts[pre]['nombre']}» no tiene avance registrado antes",
                    sorted(elems_act[act])[:50], clave=f"{act}>{pre}",
                    evidencia={"fuente": "registros.json + predecesoras del cronograma",
                               "formula": "primer_avance(actividad) < primer_avance(predecesora)",
                               "valores": {"actividad": act, "predecesora": pre, "primer_avance": f, "primer_avance_predecesora": primera.get(pre)}}))
    return out


def r06_coherencia_pu():
    """Dentro de un mismo tipo de elemento, un concreto de mayor f'c no debería costar menos por m³.
    Si ocurre, suele ser por distinto método (hecho en obra vs. premezclado/bombeado): se muestra el APU."""
    grupos = defaultdict(list)
    for it, p in D.partidas().items():
        f = _fc(p["desc"])
        if f and p["desc"].upper().startswith("CONCRETO"):
            grupos[it[:5]].append((f, it, p))
    out = []
    try:
        apu = D.apu()
    except Exception:          # sin Excel/openpyxl: la regla sigue, sin desglose
        apu = {}
    resumir = lambda it: {"rendimiento_m3_dia": apu.get(it, {}).get("rend"),
                          "recursos": [f"{d} ({q} {u})" for d, u, q in apu.get(it, {}).get("rec", {}).values()]}
    for cap, L in grupos.items():
        L.sort()
        for (f1, i1, p1), (f2, i2, p2) in zip(L, L[1:]):
            if f2 > f1 and p2["pu"] < p1["pu"]:
                ids = [e["id"] for e in D.elementos().values() if any(x["item"] in (i1, i2) for x in e["partidas"])]
                out.append(hallazgo(
                    "R06", "P.U. incoherente con el f'c", "determinista", "media",
                    f"{p2['desc'][:45]}: f'c={f2} cuesta S/ {p2['pu']:.2f}/m³, menos que f'c={f1} (S/ {p1['pu']:.2f}/m³)",
                    ids, partidas=[i1, i2],
                    evidencia={"fuente": "Presupuesto v4 › Análisis de Precios Unitarios",
                               "formula": "f'c mayor ⇒ P.U. mayor (mismo tipo de elemento)",
                               "valores": {"item_menor_fc": i1, "pu_menor_fc": p1["pu"], "item_mayor_fc": i2, "pu_mayor_fc": p2["pu"],
                                           "apu_menor_fc": resumir(i1), "apu_mayor_fc": resumir(i2)}}))
    return out


def d01_registrado_no_visto():
    """Avance por dron: elemento con metrado registrado que el último escaneo no ve (posible valorización sin ejecución)."""
    from . import escaneo
    u = escaneo.ultimo()
    if not u:
        return []
    reg = D.leer_registros()["elementos"]
    out = []
    for a in u.get("alertas_valorizacion", []):
        e = D.elementos().get(a["id"])
        if not e:
            continue
        items = sorted({it for _, it, _ in D.parsear(reg.get(str(a["id"]), {}).get("registro", ""))})
        monto = sum(q * D.partidas()[it]["pu"] for _, it, q in D.parsear(reg.get(str(a["id"]), {}).get("registro", "")) if it in D.partidas())
        out.append(hallazgo(
            "D01", "Registrado pero el dron no lo ve", "dron (Scan-vs-BIM)", a["severidad"],
            f"{e['tipo']} ({e['nivel']}): S/ {monto:,.2f} valorizados y el dron {'no lo ve' if a['estado'] == 'no_construido' else 'lo ve solo en parte'}",
            [a["id"]], partidas=items, impacto=monto, clave=u.get("fecha", ""),
            evidencia={"fuente": f"escaneo «{u.get('nombre', '')}» del {u.get('fecha', '')} + registros.json",
                       "formula": "impacto = Σ metrado registrado del elemento × P.U.  (lo que se cobraría sin ejecución)",
                       "valores": {"estado_dron": a["estado"], "visible": a["visible"], "cobertura_visible": a["cobertura_visible"],
                                   "monto_registrado": round(monto, 2), "fecha_escaneo": u.get("fecha")}}))
    return out


def d02_sin_soporte_visible():
    """Avance por dron: algo construido encima de un elemento que se ve claramente ausente (secuencia imposible)."""
    from . import escaneo
    u = escaneo.ultimo()
    if not u:
        return []
    out = []
    for a in u.get("alertas_secuencia", []):
        e = D.elementos().get(a["id"])
        if not e:
            continue
        out.append(hallazgo(
            "D02", "Construido sin soporte visible", "dron (Scan-vs-BIM)", "media",
            f"{e['tipo']} ({e['nivel']}) se ve construido pero {len(a['sin_soporte_visible'])} elemento(s) de apoyo no",
            [a["id"]] + a["sin_soporte_visible"], clave=u.get("fecha", ""),
            evidencia={"fuente": f"escaneo «{u.get('nombre', '')}» del {u.get('fecha', '')}",
                       "formula": "estado(elemento) = construido  y  estado(apoyo) = no construido con buena visibilidad",
                       "valores": {"elemento": a["id"], "apoyos_no_vistos": a["sin_soporte_visible"], "fecha_escaneo": u.get("fecha")}}))
    return out


REGLAS = [r01_solapes, r02_fc_tipo_vs_material, r03_sin_material, r04_mayor_metrado, r05_secuencia, r06_coherencia_pu,
          d01_registrado_no_visto, d02_sin_soporte_visible]


def auditar(incluir_ml=True):
    hall = []
    for r in REGLAS:
        hall += r()
    modelos = {}
    if incluir_ml:
        from . import ml
        extra, modelos = ml.hallazgos()
        hall += extra
    hall.sort(key=lambda h: (SEV[h["severidad"]], -(h["impacto_soles"] or 0)))
    resumen = defaultdict(lambda: {"n": 0, "impacto_soles": 0.0})
    for h in hall:
        r = resumen[h["regla"]]
        r["nombre"], r["metodo"] = h["nombre"], h["metodo"]
        r["n"] += 1
        r["impacto_soles"] = round(r["impacto_soles"] + (h["impacto_soles"] or 0), 2)
    return {"version_datos": D.huellas()["version_datos"], "huellas": D.huellas(),
            "resumen": dict(resumen), "modelos": modelos, "hallazgos": hall,
            "impacto_total_soles": round(sum(h["impacto_soles"] or 0 for h in hall), 2)}
