"""Capa 2 · Machine learning: «segunda opinión geométrica» sobre la clasificación de cada elemento.

Problema: metrados.py asigna cada elemento de Revit a un grupo (COL, PLA, VIG, VCH, ALI, ...) según su
categoría y el nombre de su tipo. Si el nombre está mal puesto, el elemento cae en otra partida y con otro
P.U. Este modelo NO mira el nombre del tipo: aprende del resto del modelo cómo es la GEOMETRÍA de cada grupo
(dimensiones de la caja, volumen, caras, compacidad) y señala los elementos cuya geometría se parece mucho
más a otro grupo.

Para que el juicio sea honesto se usa validación cruzada (cross_val_predict, 5 particiones): cada elemento
lo evalúa un modelo que NUNCA lo vio en entrenamiento. Se informan exactitud, F1 macro, importancia de
variables y la versión de datos. El resultado se guarda en caché por versión de datos.
"""
import json
import time
import warnings
from collections import Counter, defaultdict

from nexo_ia import datos as D

UMBRAL = 0.85                         # probabilidad mínima de la otra clase para levantar un hallazgo
INDISTINGUIBLES = {frozenset({"ALI", "LMA"})}   # losa aligerada y maciza de e=0.20: mismo sólido en Revit
VARIABLES = ["volumen_m3", "area_m2", "lado_menor_m", "lado_mayor_m", "alto_m", "cara_sup_m2", "cara_inf_m2",
             "caras_lat_m2", "compacidad", "lat_por_m3", "esbeltez_planta"]
NOMBRES_GRUPO = {"COL": "columna", "PLA": "placa", "VIG": "viga", "VCH": "viga chata/vigueta", "ALI": "losa aligerada",
                 "LMA": "losa maciza", "MUR": "muro", "ALB": "albañilería", "ESC": "escalera", "CIMM": "cimiento de muro",
                 "ZAP": "zapata", "LOSC": "losa de cimentación", "RAM": "rampa", "SUBZ": "subzapata"}


def _vector(m, categorias):
    b = m["caja_m"]
    lados = sorted([b[3] - b[0], b[4] - b[1]])
    alto = b[5] - b[2]
    c = m["caras_m2"]
    v = m["volumen_m3"] or 0.0
    return [v, m["area_m2"] or 0.0, lados[0], lados[1], alto, c["superior"], c["inferior"], c["laterales"],
            v / max(lados[0] * lados[1] * alto, 1e-6), c["laterales"] / max(v, 1e-6), lados[1] / max(lados[0], 1e-3)] \
        + [1.0 if m["categoria"] == k else 0.0 for k in categorias]


def _partida_equivalente():
    """(grupo, clase, f'c) -> item más usado, para estimar el cambio de P.U. si el grupo fuera otro."""
    from nexo_ia.auditor import _fc
    cnt = defaultdict(Counter)
    for e in D.elementos().values():
        for p in e["partidas"]:
            cnt[(e["grupo"], p["clase"], _fc(D.partidas()[p["item"]]["desc"]))][p["item"]] += 1
            cnt[(e["grupo"], p["clase"], None)][p["item"]] += 1
    return {k: c.most_common(1)[0][0] for k, c in cnt.items()}


def entrenar():
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict

    M, E = D.metrados_modelo(), D.elementos()
    ids = sorted(i for i in E if i in M)
    categorias = sorted({M[i]["categoria"] for i in ids})
    X = np.array([_vector(M[i], categorias) for i in ids], float)
    y = np.array([E[i]["grupo"] for i in ids])
    rf = RandomForestClassifier(n_estimators=300, random_state=0, class_weight="balanced", n_jobs=-1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")        # SUBZ tiene 2 elementos (< 5 particiones)
        P = cross_val_predict(rf, X, y, cv=StratifiedKFold(5, shuffle=True, random_state=0), method="predict_proba")
    clases = np.unique(y)
    pred = clases[P.argmax(1)]
    rf.fit(X, y)
    nombres = VARIABLES + [f"categoria={k}" for k in categorias]
    imp = sorted(zip(nombres, rf.feature_importances_), key=lambda x: -x[1])
    confusiones = Counter((a, b) for a, b in zip(y, pred) if a != b)
    metricas = {
        "modelo": "RandomForest (300 árboles, class_weight=balanced, random_state=0)",
        "objetivo": "grupo del elemento (asignado por metrados.py)",
        "entrada": "solo geometría y categoría de Revit (sin el nombre del tipo)",
        "validacion": "cross_val_predict, StratifiedKFold(5) — cada elemento lo juzga un modelo que no lo vio",
        "n_elementos": len(ids), "n_clases": len(clases),
        "exactitud": round(float(accuracy_score(y, pred)), 4),
        "f1_macro": round(float(f1_score(y, pred, average="macro")), 4),
        "importancia_variables": [[n, round(float(v), 4)] for n, v in imp[:8]],
        "confusiones": [[f"{a}→{b}", n] for (a, b), n in confusiones.most_common(8)],
        "umbral_hallazgo": UMBRAL, "version_datos": D.huellas()["version_datos"],
        "entrenado": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    filas = []
    for k, i in enumerate(ids):
        if pred[k] != y[k]:
            filas.append({"id": i, "grupo": str(y[k]), "predicho": str(pred[k]), "prob": round(float(P[k].max()), 3),
                          "prob_grupo_actual": round(float(P[k][list(clases).index(y[k])]), 3),
                          "geometria": dict(zip(VARIABLES, [round(float(x), 3) for x in X[k][:len(VARIABLES)]]))})
    return metricas, filas


def resultado():
    cache = D.estado() / "cache" / f"ml_{D.huellas()['version_datos']}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    metricas, filas = entrenar()
    r = {"metricas": metricas, "discrepancias": filas}
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(cache)
    return r


def hallazgos():
    from nexo_ia.auditor import _fc, hallazgo
    r = resultado()
    eq = _partida_equivalente()
    out = []
    for f in r["discrepancias"]:
        if f["prob"] < UMBRAL or frozenset({f["grupo"], f["predicho"]}) in INDISTINGUIBLES:
            continue
        e = D.elementos()[f["id"]]
        dif, cambios = 0.0, []
        for p in e["partidas"]:
            fc = _fc(D.partidas()[p["item"]]["desc"])
            alt = eq.get((f["predicho"], p["clase"], fc)) or eq.get((f["predicho"], p["clase"], None))
            if alt and alt != p["item"]:
                d = (D.partidas()[alt]["pu"] - D.partidas()[p["item"]]["pu"]) * p["metrado"]
                dif += d
                cambios.append({"clase": p["clase"], "de": p["item"], "a": alt, "metrado": p["metrado"],
                                "pu_de": D.partidas()[p["item"]]["pu"], "pu_a": D.partidas()[alt]["pu"], "diferencia": round(d, 2)})
        g = f["geometria"]
        out.append(hallazgo(
            "ML1", "Geometría no coincide con su clasificación", "machine learning", "media",
            f"{e['tipo']}: clasificado como {NOMBRES_GRUPO.get(f['grupo'], f['grupo'])}, su geometría es de "
            f"{NOMBRES_GRUPO.get(f['predicho'], f['predicho'])} ({f['prob']:.0%})",
            [f["id"]], partidas=[c["de"] for c in cambios] + [c["a"] for c in cambios], impacto=dif if cambios else None,
            confianza=f["prob"],
            evidencia={"fuente": "metrados_*.json (geometría) + modelo ML (ver métricas)",
                       "formula": "P(grupo | geometría) por validación cruzada; impacto = Σ metrado × (P.U. partida equivalente − P.U. actual)",
                       "valores": {"grupo_actual": f["grupo"], "grupo_sugerido": f["predicho"], "probabilidad": f["prob"],
                                   "prob_grupo_actual": f["prob_grupo_actual"], "lado_menor_m": g["lado_menor_m"],
                                   "lado_mayor_m": g["lado_mayor_m"], "esbeltez_planta": g["esbeltez_planta"],
                                   "alto_m": g["alto_m"], "cambios_de_partida": cambios}}))
    # agrupar por tipo: el mismo problema en N elementos del mismo tipo es UN hallazgo
    por_tipo = defaultdict(list)
    for h in out:
        por_tipo[(D.elementos()[h["elementos"][0]]["tipo"], h["evidencia"]["valores"]["grupo_sugerido"])].append(h)
    agrupados = []
    for (tipo, _), L in por_tipo.items():
        h = L[0]
        if len(L) > 1:
            h = dict(h, id=f"ML1-{L[0]['elementos'][0]}", elementos=[x["elementos"][0] for x in L],
                     titulo=h["titulo"].replace(f"{tipo}:", f"{tipo} ({len(L)} elementos):"),
                     impacto_soles=round(sum(x["impacto_soles"] or 0 for x in L), 2),
                     confianza=round(min(x["confianza"] for x in L), 3))
        agrupados.append(h)
    return agrupados, {"ML1": r["metricas"]}
