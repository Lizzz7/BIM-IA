"""Parte diario asistido: lo que escribe (o dicta) el residente -> metrado por elemento listo para registrar.

  texto libre ──► [intérprete: LLM o reglas] ──► INTENCIÓN (JSON con valores de una lista cerrada)
              ──► [resolución determinista] ──► elementos de Revit + cantidades (saldo × %)
              ──► POST /api/metrado {simular:true} (validación del propio sistema) ──► el ingeniero confirma

El intérprete nunca devuelve IDs ni cantidades: solo paquete, sector, grupos, clase y porcentaje,
validados contra los valores que existen en el modelo. Las cantidades salen de los datos.
"""
import json
import re
import unicodedata
from datetime import date

from . import bitacora, llm
from . import datos as D
from .ml import NOMBRES_GRUPO

CLASES = ["concreto", "encofrado", "acero", "ladrillo", "muro"]
VERTICALES = {"COL", "PLA", "MUR", "ALB", "CIMM"}


def catalogo():
    """Paquetes del cronograma + paquetes que solo existen en los elementos (p. ej. anillos de muros anclados)."""
    E = list(D.elementos().values())
    paq, vistos = [], set()
    for p in D.cronograma()["paquetes"]:
        gr = sorted({e["grupo"] for e in E if e["paquete"] == p["id"]})
        if gr:
            paq.append({"id": p["id"], "nombre": p["nombre"], "nivel_verticales": p.get("vertical"), "nivel_techo": p.get("horizontal"), "grupos": gr})
            vistos.add(p["id"])
    for pid in sorted({e["paquete"] for e in E} - vistos):
        niveles = sorted({e["nivel"] for e in E if e["paquete"] == pid})
        paq.append({"id": pid, "nombre": f"{pid} ({', '.join(niveles)})", "nivel_verticales": None, "nivel_techo": None,
                    "grupos": sorted({e["grupo"] for e in E if e["paquete"] == pid})})
    return {"paquetes": paq, "grupos": {g: NOMBRES_GRUPO.get(g, g) for g in sorted({e["grupo"] for e in E})},
            "sectores": ["A", "B", "ambos"], "clases": CLASES}


def esquema():
    c = catalogo()
    return {"type": "object", "required": ["trabajos", "dudas"], "properties": {
        "fecha": {"type": "string"},
        "trabajos": {"type": "array", "items": {"type": "object", "required": ["paquete", "sector", "grupos", "clase", "porcentaje"], "properties": {
            "paquete": {"type": "string", "enum": [p["id"] for p in c["paquetes"]]},
            "sector": {"type": "string", "enum": c["sectores"]},
            "grupos": {"type": "array", "items": {"type": "string", "enum": list(c["grupos"])}},
            "clase": {"type": "string", "enum": CLASES},
            "porcentaje": {"type": "number"},
            "texto_origen": {"type": "string"}}}},
        "dudas": {"type": "array", "items": {"type": "string"}}}}


SISTEMA = """Eres asistente de un residente de obra en Perú. Conviertes el parte diario (texto libre) en una lista de
trabajos ejecutados, usando SOLO los identificadores del catálogo del modelo BIM que se te da.
Cómo se habla en obra y cómo se traduce:
- "piso N" o "columnas/placas del piso N" = elementos verticales: el paquete cuyo nivel_verticales es "0N. NFP".
- "techo del piso N", "losa/vigas/aligerado del piso N" = el paquete llamado "Techo de Piso N".
- "vaciado/vaciamos/concreto" = concreto; "encofrado" = encofrado; "acero/fierro/armadura/habilitado" = acero; "ladrillo de techo" = ladrillo.
- Si no se menciona sector usa "ambos". Si no se menciona porcentaje usa 100. "la mitad" = 50.
- "techo" o "losa" sin más incluye vigas, viguetas/vigas chatas, losas aligeradas y macizas y escaleras que existan en ese paquete.
- No inventes trabajos. Si algo es ambiguo, NO lo incluyas: escríbelo en "dudas"."""


# ---------------------------------------------------------------- intérprete por reglas (base sin LLM)
def _norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


PAL_GRUPO = [(r"columna", ["COL"]), (r"placa", ["PLA"]), (r"muro", ["MUR"]), (r"viga(s)? chata|vigueta", ["VCH"]),
             (r"\bvigas?\b(?! chata)", ["VIG"]), (r"aligerad", ["ALI"]), (r"losa(s)? maciza", ["LMA"]), (r"escalera", ["ESC"]),
             (r"zapata", ["ZAP"]), (r"cimiento", ["CIMM"]), (r"losa de cimentacion|cisterna", ["LOSC"])]
PAL_CLASE = [(r"vaci|concret", "concreto"), (r"encofr", "encofrado"), (r"acero|fierro|armad|habilit", "acero"), (r"ladrillo", "ladrillo")]


ORDINALES = {"primer": 1, "primero": 1, "segundo": 2, "tercer": 3, "tercero": 3, "cuarto": 4, "quinto": 5, "sexto": 6,
             "septimo": 7, "setimo": 7, "octavo": 8, "noveno": 9, "decimo": 10}
NOMBRE_EN_TEXTO = {"COL": "columnas", "PLA": "placas", "MUR": "muros", "VIG": "vigas", "VCH": "viguetas", "ALI": "losa aligerada",
                   "LMA": "losa maciza", "ESC": "escalera", "ZAP": "zapatas", "CIMM": "cimientos", "LOSC": "losa de cimentacion",
                   "RAM": "rampa", "ALB": "muros de albanileria", "SUBZ": "subzapatas"}
VERBO = {"concreto": "Vaciado de", "encofrado": "Encofrado de", "acero": "Acero de", "ladrillo": "Ladrillo de", "muro": "Asentado de"}


def normalizar(t):
    """Cómo se habla en obra -> forma que entienden las reglas: «3er piso», «segundo piso», «lado A», «piso tercero»."""
    t = _norm(t)
    t = re.sub(r"\b(\d{1,2})\s*(?:er|ro|do|to|mo|vo|no|avo|°|º|\.?o)\b", r"\1", t)
    t = re.sub(r"\b(" + "|".join(ORDINALES) + r")\b", lambda m: str(ORDINALES[m.group(1)]), t)
    t = re.sub(r"\b(\d{1,2})\s+(?:piso|nivel)\b", r"piso \1", t)
    t = re.sub(r"\b(?:piso|nivel)\s+(\d{1,2})\b", r"piso \1", t)
    t = re.sub(r"\b(?:lado|zona|frente)\s+([ab])\b", r"sector \1", t)
    return t


def _lugar(p):
    """Texto del nivel de un paquete, que las propias reglas vuelven a entender ('piso 2', 'semisotano', 'sotano 1')."""
    n = _norm(p.get("nivel_verticales") or "").upper()
    m = re.match(r"0?(\d+)\. NFP", n)
    if m:
        return f"del piso {int(m.group(1))}"
    if "SEMISOTANO" in n:
        return "del semisotano"
    m = re.search(r"SOTANO (\d)", n)
    return f"del sotano {m.group(1)}" if m else ""


def _paquete_sin_nivel(grupos, paq):
    """Cimentaciones y anillos de muros no tienen 'piso': si solo un paquete sin nivel tiene esos grupos, es ese."""
    c = [p["id"] for p in paq.values() if not p["nivel_verticales"] and set(grupos) & set(p["grupos"])]
    return c[0] if len(c) == 1 else None


def _sugerir(frase, pid, clases, grupos, paq):
    """Hasta 3 frases completas que sí se pueden registrar, armadas con el catálogo del modelo."""
    sector = re.search(r"sector ([ab])\b", frase)
    sec = f" sector {sector.group(1).upper()}" if sector else ""
    out = []
    if grupos and not clases:
        cands = [pid] if pid else [p for p in paq if set(grupos) & set(paq[p]["grupos"])][:1]
        for c in ("concreto", "encofrado", "acero"):
            for q in cands:
                gs = [g for g in grupos if g in paq[q]["grupos"]]
                if gs:
                    out.append(f"{VERBO[c]} {' y '.join(NOMBRE_EN_TEXTO.get(g, g) for g in gs)} {_lugar(paq[q])}{sec}".replace("  ", " ").strip())
    elif grupos and clases and not pid:
        for q in [p for p in paq if set(grupos) & set(paq[p]["grupos"]) and paq[p]["nivel_verticales"]][:3]:
            out.append(f"{VERBO[clases[0]]} {' y '.join(NOMBRE_EN_TEXTO.get(g, g) for g in grupos if g in paq[q]['grupos'])} {_lugar(paq[q])}{sec}")
    elif pid and clases and not grupos:
        for g in [g for g in paq[pid]["grupos"] if g in ("COL", "PLA", "VIG", "ALI")][:3]:
            out.append(f"{VERBO[clases[0]]} {NOMBRE_EN_TEXTO[g]} {_lugar(paq[pid])}{sec}")
    return [x[0].upper() + x[1:] for x in out[:3]]


def _falta(pid, clases, grupos):
    f = []
    if not clases:
        f.append("qué trabajo (vaciado, encofrado, acero, ladrillo)")
    if not grupos:
        f.append("qué elementos (columnas, placas, vigas, losa…)")
    if not pid:
        f.append("en qué nivel (p. ej. «piso 3», «semisótano»)")
    return f


def interpretar_reglas(texto):
    t = normalizar(texto)
    paq = {p["id"]: p for p in catalogo()["paquetes"]}
    trabajos, dudas, sugerencias = [], [], []
    for frase in re.split(r"[.;\n]| y se | ademas ", t):
        if not frase.strip():
            continue
        clases = [c for pat, c in PAL_CLASE if re.search(pat, frase)]
        grupos = [g for pat, gs in PAL_GRUPO for g in gs if re.search(pat, frase)]
        pid = _paquete_por_nivel(frase, paq)
        if pid and not grupos and re.search(r"\btecho\b|\blosa\b", frase):   # "techo" sin más = todo lo horizontal
            grupos = [g for g in paq[pid]["grupos"] if g not in VERTICALES]
        if not pid and grupos:
            pid = _paquete_sin_nivel(grupos, paq)
        if not (pid and clases and grupos):
            if not (clases or grupos or pid):
                if re.search(r"llovi|no se trabaj|paraliz|feriado|descanso", frase):
                    continue                                         # sin trabajo: nada que registrar ni preguntar
                dudas.append(f"No encontré trabajos en «{frase.strip()}»")
            else:
                dudas.append(f"En «{frase.strip()}» falta " + " y ".join(_falta(pid, clases, grupos)))
                sugerencias += _sugerir(frase, pid, clases, grupos, paq)
            continue
        sec = re.search(r"sector ([ab])\b", frase)
        pct = re.search(r"(\d{1,3})\s*%", frase)
        porcentaje = float(pct.group(1)) if pct else 50.0 if "mitad" in frase else 100.0
        for c in clases:
            trabajos.append({"paquete": pid, "sector": sec.group(1).upper() if sec else "ambos",
                             "grupos": sorted(set(g for g in grupos if g in paq[pid]["grupos"])), "clase": c,
                             "porcentaje": porcentaje, "texto_origen": frase.strip()})
    return {"trabajos": [x for x in trabajos if x["grupos"]], "dudas": dudas, "sugerencias": list(dict.fromkeys(sugerencias))[:3]}


def _paquete_por_nivel(frase, paq):
    """'piso 3', 'techo del piso 3', 'semisótano', 'sótano 1' -> paquete cuyo nivel de verticales es ese nivel.
    En este cronograma «Techo de X» agrupa las verticales de X y su techo, así que ambos caen en el mismo paquete.
    Se busca en los niveles reales del modelo (no hay paquetes escritos a mano)."""
    m = re.search(r"piso (\d+)", frase)
    if m:
        objetivo = lambda n: re.match(rf"0?{int(m.group(1))}\. ", n or "")
    elif "semisotano" in frase:
        objetivo = lambda n: "SEMISOTANO" in _norm(n or "").upper()
    else:
        m = re.search(r"sotano (\d)", frase)
        if not m:
            return None
        objetivo = lambda n: re.search(rf"(?<!SEMI)SOTANO {m.group(1)}", _norm(n or "").upper())
    return next((p["id"] for p in paq.values() if objetivo(p["nivel_verticales"])), None)


# ---------------------------------------------------------------- resolución determinista
def resolver(intencion):
    ej = D.ejecutado_por_elemento()
    registros, resumen, problemas = [], [], []
    for t in intencion["trabajos"]:
        els = [e for e in D.elementos().values() if e["paquete"] == t["paquete"] and e["grupo"] in t["grupos"]
               and (t["sector"] == "ambos" or e["sector"] == t["sector"])]
        if not els:
            problemas.append(f"Ningún elemento de {t['grupos']} en {t['paquete']} sector {t['sector']}")
            continue
        pct = max(0.0, min(100.0, float(t["porcentaje"]))) / 100
        por_item, ids, sin_saldo = {}, [], 0
        for e in els:
            for p in e["partidas"]:
                if p["clase"] != t["clase"]:
                    continue
                # "avanzamos el 50 %" = 50 % del metrado total del elemento, nunca más que lo que falta
                saldo = p["metrado"] - ej.get(e["id"], {}).get(p["item"], 0.0)
                q = round(min(p["metrado"] * pct, saldo), 6)
                if q <= 1e-9:
                    sin_saldo += 1
                    continue
                registros.append({"id": e["id"], "item": p["item"], "cantidad": q})
                por_item[p["item"]] = por_item.get(p["item"], 0.0) + q
                ids.append(e["id"])
        resumen.append({**t, "n_elementos": len(set(ids)), "sin_saldo": sin_saldo, "elementos": sorted(set(ids)),
                        "partidas": [{"item": i, "desc": D.partidas()[i]["desc"], "und": D.partidas()[i]["und"], "cantidad": round(q, 4),
                                      "monto": round(q * D.partidas()[i]["pu"], 2)} for i, q in sorted(por_item.items())]})
    return {"registros": registros, "resumen": resumen, "problemas": problemas,
            "monto_total": round(sum(p["monto"] for r in resumen for p in r["partidas"]), 2)}


def res_vacio(intencion):
    return not intencion.get("trabajos")


def procesar(texto, fecha=None, usar_llm=True):
    fecha = fecha or date.today().isoformat()
    meta = {"proveedor": "reglas", "modelo": "reglas"}
    cat = catalogo()
    validos = {p["id"]: set(p["grupos"]) for p in cat["paquetes"]}

    def chequeo(obj):
        prob = []
        for t in obj["trabajos"]:
            fuera = set(t["grupos"]) - validos.get(t["paquete"], set())
            if fuera:
                prob.append(f"el paquete {t['paquete']} no tiene elementos de los grupos {sorted(fuera)}")
            if not 0 < t["porcentaje"] <= 100:
                prob.append(f"porcentaje fuera de rango: {t['porcentaje']}")
        return prob

    origen = "reglas"
    if usar_llm and llm.disponible():
        try:
            intencion, meta = llm.pedir_json(SISTEMA, json.dumps({"catalogo": cat, "fecha_del_parte": fecha, "parte_diario": texto},
                                                                 ensure_ascii=False), esquema(), chequeo)
            origen = "llm" if meta["aceptado"] else "reglas (el LLM no pasó la validación)"
            if not meta["aceptado"]:
                intencion = interpretar_reglas(texto)
        except llm.ErrorLLM as e:
            intencion, origen = interpretar_reglas(texto), f"reglas (error LLM: {e})"
    else:
        intencion = interpretar_reglas(texto)
    res = resolver(intencion)
    intencion.setdefault("sugerencias", interpretar_reglas(texto).get("sugerencias", []) if res_vacio(intencion) else [])
    out = {"fecha": fecha, "texto": texto, "origen": origen, "proveedor": meta.get("proveedor"), "modelo": meta.get("modelo"),
           "intencion": intencion, **res, "version_datos": D.huellas()["version_datos"]}
    bitacora.anotar("parte_diario", texto=texto, fecha=fecha, origen=origen, proveedor=meta.get("proveedor"),
                    modelo=meta.get("modelo"), intencion=intencion, n_registros=len(res["registros"]),
                    monto_total=res["monto_total"], intentos=meta.get("intentos"), ms=meta.get("ms"))
    return out
