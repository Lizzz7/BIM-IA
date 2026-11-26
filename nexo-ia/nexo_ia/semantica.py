"""Búsqueda de candidatas: restricciones duras, embeddings opcionales y TF-IDF local."""
from collections import Counter
import math
import re

from .motor import UNIDADES_CLASE, resistencia, texto, unidad


def caracteristicas(s):
    palabras = re.findall(r"[a-z0-9]+", texto(s))
    partes = ["w:" + p for p in palabras]
    for p in palabras:
        if len(p) >= 4:
            partes.extend("c:" + p[i:i+3] for i in range(len(p)-2))
    return Counter(partes)


def coseno(a, b):
    if len(a) != len(b):
        raise ValueError("Dimensiones diferentes.")
    den = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / den if den else 0.0


def similitudes_locales(consulta, documentos):
    corpus = [caracteristicas(s) for s in documentos]
    q = caracteristicas(consulta)
    frecuencias = Counter(t for d in corpus for t in d)
    def vector(d):
        return {t: (1 + math.log(n)) * (math.log((1 + len(corpus)) / (1 + frecuencias[t])) + 1)
                for t, n in d.items()}
    qv = vector(q)
    def sim(d):
        dv = vector(d)
        den = math.sqrt(sum(v*v for v in qv.values()) * sum(v*v for v in dv.values()))
        return sum(v*dv.get(t, 0) for t, v in qv.items()) / den if den else 0.0
    return [sim(d) for d in corpus]


def sugerir(base, crudos, eid, clase, proveedor, usar_ia=False):
    if clase not in UNIDADES_CLASE:
        raise ValueError("Elige concreto, encofrado, acero o ladrillo.")
    e = next((e for e in base["elementos"] if e["id"] == eid), None)
    if not e:
        raise ValueError("Elemento inexistente.")
    raw = crudos.get(eid, {})
    materiales = " | ".join(m.get("material") or "" for m in raw.get("materiales", []))
    fc = resistencia(materiales) if clase == "concreto" else None
    candidatas = [p for p in base["partidas"]
                  if unidad(p["und"]) == UNIDADES_CLASE[clase]
                  and clase in texto(p["desc"])
                  and (fc is None or resistencia(p["desc"]) == fc)]
    consulta = f'{clase} {e.get("tipo", "")} {e.get("grupo", "")} {raw.get("familia", "")} {materiales}'
    algoritmo, aviso = "TF-IDF léxico local (sin modelo de IA)", None
    if candidatas:
        docs = [p["desc"] for p in candidatas]
        if usar_ia:
            if not proveedor.estado()["embeddings_configurados"]:
                raise ValueError("Configura embeddings para utilizar búsqueda semántica de IA.")
            vs = proveedor.vectores([consulta] + docs)
            puntajes = [coseno(vs[0], v) for v in vs[1:]]
            algoritmo = "Embeddings + similitud coseno · " + proveedor.embedding
        else:
            puntajes = similitudes_locales(consulta, docs)
        ordenadas = sorted(zip(candidatas, puntajes), key=lambda x: -x[1])[:3]
    else:
        ordenadas = []
        aviso = "No existen candidatas que cumplan las restricciones; no se fuerza una asignación."
    return {"ok": True, "element_id": eid, "clase": clase, "consulta": consulta,
            "algoritmo": algoritmo, "restricciones": {"unidad": UNIDADES_CLASE[clase], "fc_material": fc},
            "actuales": [p["item"] for p in e["partidas"] if p.get("clase") == clase],
            "candidatas": [{"item": p["item"], "desc": p["desc"], "und": p["und"], "pu": p["pu"],
                           "similitud": round(s, 4)} for p, s in ordenadas],
            "aviso": aviso,
            "limite": "La similitud no es probabilidad de acierto. Son propuestas: no modifican vínculos, "
                      "metrados ni valorizaciones. Sin material explícito no se comprueba resistencia."}
