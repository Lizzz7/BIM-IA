"""Preguntas de costos y presupuesto en el chat del parte diario («¿cuánto llevamos valorizado?»).

Respuestas DETERMINISTAS armadas con costos.resumen(): cada cifra sale del presupuesto, el cronograma, los registros,
el último escaneo o la auditoría, con la misma fórmula que el panel. No se usa LLM para los números.
"""
import re

from nexo_ia import costos
from nexo_ia import datos as D
from nexo_ia.parte_diario import PAL_CLASE, _norm

PREGUNTA = re.compile(r"^\s*(cuanto|cuantos|cual|cuales|que|como|estamos|vamos|dame|muestra|muestrame|dime|resumen|hay)\b"
                      r"|\b(valoriz|presupuest|spi|atrasad|adelantad|saldo|riesgo|costo directo|igv|utilidad|gastos generales"
                      r"|programado|hallazg|cobrar|pagar|monto|plata|soles)")


def es_pregunta(texto):
    t = _norm(texto)
    if "?" in texto or "¿" in texto:
        return True
    hay_trabajo = any(re.search(p, t) for p, _ in PAL_CLASE)
    return bool(PREGUNTA.search(t)) and not hay_trabajo


def _s(x):
    return "—" if x is None else f"S/ {x:,.2f}"


def responder(texto, corte=None, escaneo_ultimo=None, auditoria=None):
    t = _norm(texto)
    r = costos.resumen(corte, escaneo_ultimo=escaneo_ultimo, auditoria=auditoria)
    cifras, tema = [], "resumen"
    m = re.search(r"\b(\d{2}(?:\.\d{2}){1,2})\b", texto)
    caps = {k: _norm(v) for k, v in (D.datos_base().get("capitulos") or {}).items() if len(k) == 2}
    puntaje = {k: sum(w in t for w in v.split() if len(w) > 4) for k, v in caps.items()}
    cap = max(puntaje, key=lambda k: (puntaje[k], -int(k))) if puntaje and max(puntaje.values()) else None
    if m and m.group(1) in D.partidas():
        tema = "partida"
        it, p = m.group(1), D.partidas()[m.group(1)]
        ej = sum(q for f, _, i, q in costos.movimientos() if i == it and f <= r["corte"])
        txt = (f"Partida {it} {p['desc'].lower()}: contrato {p['metrado']:,.2f} {p['und']} × {_s(p['pu'])} = {_s(p['metrado'] * p['pu'])}. "
               f"Ejecutado al {r['corte']}: {ej:,.2f} {p['und']} ({_s(ej * p['pu'])}); saldo {p['metrado'] - ej:,.2f} {p['und']} "
               f"({_s((p['metrado'] - ej) * p['pu'])}).")
        cifras = [("Contrato", p["metrado"] * p["pu"]), ("Ejecutado", ej * p["pu"]), ("Saldo", (p["metrado"] - ej) * p["pu"])]
    elif re.search(r"riesgo|dron|no (lo )?ve|verific|confirm", t):
        tema = "dron"
        d = r["dron"]
        if not d:
            txt = "Todavía no hay un escaneo del dron procesado para esta obra: súbelo en Parte diario › Avance por dron o usa la simulación."
        else:
            txt = (f"Según el escaneo del {d['fecha']}: {_s(d['confirmado'])} de lo valorizado está confirmado por el dron, "
                   f"{_s(d['en_riesgo'])} está en riesgo ({d['n_alertas']} elemento(s) registrados que no se ven) y el dron propone "
                   f"{_s(d['por_valorizar'])} por valorizar.")
            cifras = [("Confirmado", d["confirmado"]), ("En riesgo", d["en_riesgo"]), ("Por valorizar", d["por_valorizar"])]
    elif re.search(r"hallazg|auditor|observac|error", t):
        tema = "hallazgos"
        h = r["hallazgos"] or {}
        txt = (f"La auditoría tiene {h.get('n_pendientes', 0)} hallazgo(s) sin revisar ({h.get('n_altas_pendientes', 0)} de severidad alta) "
               f"por {_s(h.get('pendiente'))}, y {h.get('n_aceptados', 0)} aceptado(s) por {_s(h.get('aceptado'))}. Revísalos en Control.")
        cifras = [("Pendiente", h.get("pendiente")), ("Aceptado", h.get("aceptado"))]
    elif re.search(r"spi|atras|adelant|tiempo|plazo|programado|cronograma", t):
        tema = "plazo"
        txt = (f"Al {r['corte']} se programó {_s(r['programado'])} ({r['programado_pct']} %) y se valorizó {_s(r['valorizado'])} "
               f"({r['avance_pct']} %): SPI {r['spi'] if r['spi'] is not None else '—'}, {r['estado_plazo'] or 'sin programado aún'}.")
        cifras = [("Programado", r["programado"]), ("Valorizado", r["valorizado"])]
    elif re.search(r"presupuest|total|costo directo|igv|utilidad|gastos generales|contrato", t) and not re.search(r"\bmes\b", t):
        tema = "presupuesto"
        b = r["presupuesto"]
        txt = (f"Presupuesto: costo directo {_s(b['cd'])} + gastos generales {_s(b['gg'])} + utilidad {_s(b['ut'])} = {_s(b['subtotal'])}; "
               f"+ IGV {_s(b['igv'])} = {_s(b['bruta'])}. {r['modelo']['pct_modelo']} % del costo directo sale de elementos del modelo de Revit.")
        cifras = [("Costo directo", b["cd"]), ("Total con IGV", b["bruta"])]
    elif cap:
        tema = "capitulo"
        c = next(x for x in r["por_capitulo"] if x["capitulo"] == cap)
        txt = (f"Capítulo {cap} {c['nombre'].lower()}: presupuesto {_s(c['presupuesto'])}, valorizado {_s(c['valorizado'])} "
               f"({c['avance_pct']} %), saldo {_s(c['saldo'])}" + (f", en riesgo {_s(c['en_riesgo'])}." if c["en_riesgo"] else "."))
        cifras = [("Presupuesto", c["presupuesto"]), ("Valorizado", c["valorizado"]), ("Saldo", c["saldo"])]
    else:
        tema = "valorizacion"
        per = r["periodo"] or {}
        vm = per.get("valorizacion_mes") or costos.valorizacion(0)
        txt = (f"Valorización N° {per.get('n', '—')} ({per.get('desde', '')} a {r['corte']}): costo directo {_s(per.get('valorizado_mes'))} "
               f"de {_s(per.get('programado_mes'))} programados; con GG, utilidad e IGV {_s(vm['bruta'])}. "
               f"Acumulado {_s(r['valorizado'])} ({r['avance_pct']} % del presupuesto); neto recomendado {_s(r['neto_recomendado'])}.")
        cifras = [("Mes (CD)", per.get("valorizado_mes")), ("Mes con IGV", vm["bruta"]), ("Acumulado", r["valorizado"]),
                  ("Neto recomendado", r["neto_recomendado"])]
    return {"tipo": "consulta", "tema": tema, "texto": txt, "corte": r["corte"],
            "cifras": [{"etiqueta": a, "valor": None if b is None else round(b, 2)} for a, b in cifras], "origen": "costos (determinista)"}
