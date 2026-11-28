"""Avance por dron (Scan-vs-BIM): nube de puntos de la obra vs. modelo de Revit -> estado de cada elemento -> metrado.

  nube (.ply/.las/.xyz de WebODM o ReCap)
     ──► alineación ICP contra el modelo (corrige el georreferenciado imperfecto)
     ──► por elemento: % de su superficie con puntos a < tol  (cobertura)
     ──► visibilidad: qué parte del elemento PUEDE ver el dron (z-buffer desde las cámaras del plan de vuelo)
     ──► estado:  construido · no construido · dudoso · no observable
     ──► reglas de secuencia constructiva: si lo de arriba está construido, lo que lo soporta también (inferido)
     ──► cruce con los registros de metrado:
           visto y sin registrar  -> PROPUESTA de registro (el residente valida y registra, como el parte diario)
           registrado y no visto  -> ALERTA (posible valorización sin ejecución)

Todo es determinista (geometría + reglas). Nada se registra solo: la salida tiene el mismo formato que
parte_diario.resolver() y pasa por POST /api/metrado {simular:true} antes de registrar.
"""
import contextvars
import json
import time
from datetime import date, datetime

import numpy as np
from scipy.spatial import cKDTree

from . import bitacora, nube_io
from . import datos as D
from .ml import NOMBRES_GRUPO

ESPACIADO_REF = 0.12        # m entre puntos de referencia sobre el modelo
TOL = 0.10                  # m: un punto "toca" el elemento si está a menos de esto
COB_CONSTRUIDO = 0.45       # fracción de la parte visible cubierta para decir "construido"
COB_TOTAL_CONSTRUIDO = 0.30  # o fracción de todo el elemento (cuando se ve más de lo que el modelo completo deja ver)
COB_DUDOSO = 0.15
MIN_VISIBLES = 8            # puntos de referencia visibles mínimos para poder juzgar
MIN_FRACCION_VISIBLE = 0.10  # y fracción mínima del elemento a la vista (si se ve <10 %, lo "visto" suele ser la cara
                             # que comparte con un vecino construido: no alcanza para juzgar)
ESTADOS = ["construido", "inferido", "dudoso", "no_construido", "no_observable"]
_cache = {}


# ---------------------------------------------------------------- geometría del modelo
def triangulos():
    """{id: array (n,3,3)} desde la geometría de la instantánea (la misma que dibuja el visor 3D)."""
    k = ("tri", D.huellas()["version_datos"])
    if k not in _cache:
        els = D.elementos()
        _cache[k] = {g["id"]: np.asarray(g["v"], float).reshape(-1, 3, 3)
                     for g in D.actual().instantanea["geo"]["elementos"] if g["id"] in els and len(g["v"]) >= 9}
    return _cache[k]


def muestrear_superficie(T, espaciado, rng, minimo=6):
    """Puntos al azar sobre los triángulos T (n,3,3), ~1 punto por espaciado² m²."""
    a = 0.5 * np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
    if a.sum() <= 0:
        return np.empty((0, 3))
    n = max(int(round(a.sum() / espaciado ** 2)), minimo)
    t = rng.choice(len(T), n, p=a / a.sum())
    u, v = rng.random(n), rng.random(n)
    f = u + v > 1
    u[f], v[f] = 1 - u[f], 1 - v[f]
    return T[t, 0] + u[:, None] * (T[t, 1] - T[t, 0]) + v[:, None] * (T[t, 2] - T[t, 0])


def referencia():
    """Puntos de referencia del modelo completo + dueño de cada punto + cajas por elemento (en caché por versión)."""
    k = ("ref", D.huellas()["version_datos"], ESPACIADO_REF)
    if k not in _cache:
        rng = np.random.default_rng(0)
        tri = triangulos()
        ids = sorted(tri)
        P, dueno, cajas = [], [], []
        for i, eid in enumerate(ids):
            p = muestrear_superficie(tri[eid], ESPACIADO_REF, rng)
            P.append(p); dueno.append(np.full(len(p), i))
            v = tri[eid].reshape(-1, 3)
            cajas.append(np.r_[v.min(0), v.max(0)])
        P, dueno = np.vstack(P), np.concatenate(dueno)
        # Puntos PROPIOS: los que no están pegados a otro elemento. Las caras de contacto (viga contra columna) y los
        # sólidos superpuestos del modelo (viga dentro de la losa, ver R01) se cubrirían con los puntos del vecino.
        d, j = cKDTree(P).query(P, k=12, distance_upper_bound=TOL * 1.2)
        vecino = np.where(np.isfinite(d), dueno[np.minimum(j, len(P) - 1)], -1)
        compartido = ((vecino != dueno[:, None]) & (vecino >= 0)).any(1)
        # anfitrión: el vecino con el que más comparte cada elemento (para los que quedan casi enteros dentro de otro)
        anfitrion = {}
        for i in np.unique(dueno[compartido]):
            v = vecino[(dueno == i) & compartido]
            v = v[(v >= 0) & (v != i)]
            if len(v):
                anfitrion[int(i)] = int(np.bincount(v).argmax())
        _cache[k] = {"ids": ids, "P": P, "dueno": dueno, "propio": ~compartido, "anfitrion": anfitrion, "cajas": np.array(cajas)}
    return _cache[k]


# ---------------------------------------------------------------- cámaras y visibilidad
def camaras(bmin, bmax, z_suelo=0.0, n_orbita=24):
    """Posiciones de cámara de un plan de vuelo tipo (ver 7_Dron/planificador_dron.py):
    malla nadir 4x4 a 25 m sobre lo más alto + dos órbitas oblicuas."""
    bmin, bmax = np.asarray(bmin, float), np.asarray(bmax, float)
    c = (bmin + bmax) / 2
    top = max(bmax[2], z_suelo)
    cams = [(x, y, top + 25) for x in np.linspace(bmin[0] - 5, bmax[0] + 5, 4) for y in np.linspace(bmin[1] - 5, bmax[1] + 5, 4)]
    r = np.hypot(*(bmax[:2] - bmin[:2])) / 2 + 12
    for dz in (8, 18):
        cams += [(c[0] + r * np.cos(t), c[1] + r * np.sin(t), top + dz) for t in np.linspace(0, 2 * np.pi, n_orbita, endpoint=False)]
    return np.array(cams), c


def visibilidad(P, cams, objetivo, espaciado, ocluyentes=None):
    """Para cada punto de P: ¿lo ve al menos una cámara? z-buffer angular por cámara (sin GPU, solo numpy).
    Sin `ocluyentes`, los propios puntos P se tapan entre sí. Con `ocluyentes` (la nube del dron), P solo se tapa con
    lo que REALMENTE hay en la obra: un punto es visible si en su píxel no hay nada delante (o está a la misma distancia)."""
    vis = np.zeros(len(P), bool)
    Q = P if ocluyentes is None else np.vstack([ocluyentes, P])
    es_p = np.r_[np.zeros(0 if ocluyentes is None else len(ocluyentes), bool), np.ones(len(P), bool)]
    for c in cams:
        d = Q - c
        f = np.asarray(objetivo) - c
        f /= np.linalg.norm(f)
        r = np.cross(f, [0, 0, 1.0]); r = r / np.linalg.norm(r) if np.linalg.norm(r) > 1e-6 else np.array([1.0, 0, 0])
        u = np.cross(r, f)
        x, y, z = d @ r, d @ u, d @ f
        dist = np.linalg.norm(d, axis=1)
        ok = z > 0.5
        if not ok.any():
            continue
        alfa = 2.2 * espaciado / max(np.percentile(dist[ok], 2), 1.0)       # tamaño angular del píxel
        ix = np.floor(np.arctan2(x, z) / alfa).astype(np.int64)
        iy = np.floor(np.arctan2(y, np.hypot(x, z)) / alfa).astype(np.int64)
        clave = (ix - ix.min()) * (iy.max() - iy.min() + 1) + (iy - iy.min())
        idx = np.where(ok)[0]
        orden = idx[np.argsort(clave[idx], kind="stable")]
        cl = clave[orden]
        cortes = np.r_[0, np.flatnonzero(np.diff(cl)) + 1]
        grupo = np.repeat(np.arange(len(cortes)), np.diff(np.r_[cortes, len(orden)]))
        do = np.where(es_p[orden] & (ocluyentes is not None), np.inf, dist[orden])   # P no tapa si hay ocluyentes
        zmin = np.minimum.reduceat(do, cortes)
        tol = 0.10 + 1.5 * alfa * dist[orden]
        visto = (dist[orden] <= zmin[grupo] + tol) & es_p[orden]
        vis[orden[visto] - (len(Q) - len(P))] = True
    return vis


def visibilidad_modelo():
    """Visibilidad de los puntos de referencia con el modelo COMPLETO como obstáculo (en caché por versión)."""
    k = ("vis", D.huellas()["version_datos"], ESPACIADO_REF)
    if k not in _cache:
        ref = referencia()
        cams, c = camaras(ref["P"].min(0), ref["P"].max(0))
        _cache[k] = visibilidad(ref["P"], cams, c, ESPACIADO_REF)
    return _cache[k]


# ---------------------------------------------------------------- alineación
def icp(fuente, destino, iteraciones=40, distancias=(1.0, 0.5, 0.25, 0.12)):
    """ICP rígido punto a punto (Kabsch) con distancia máxima decreciente. Devuelve T (4x4), rmse y fracción emparejada."""
    arbol = cKDTree(destino)
    T = np.eye(4)
    S = fuente.copy()
    rmse, frac = None, 0.0
    for dmax in distancias:
        for _ in range(iteraciones // len(distancias)):
            d, j = arbol.query(S, distance_upper_bound=dmax)
            m = np.isfinite(d)
            if m.sum() < 50:
                break
            a, b = S[m], destino[j[m]]
            ca, cb = a.mean(0), b.mean(0)
            U, _, Vt = np.linalg.svd((a - ca).T @ (b - cb))
            R = Vt.T @ U.T
            if np.linalg.det(R) < 0:
                Vt[-1] *= -1
                R = Vt.T @ U.T
            t = cb - R @ ca
            S = S @ R.T + t
            Ti = np.eye(4); Ti[:3, :3], Ti[:3, 3] = R, t
            T = Ti @ T
            rmse, frac = float(np.sqrt((d[m] ** 2).mean())), float(m.mean())
            if np.linalg.norm(t) < 1e-4 and abs(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))) < 1e-5:
                break
    return T, rmse, frac


def aplicar(T, P):
    return P @ T[:3, :3].T + T[:3, 3]


# ---------------------------------------------------------------- comparación
def _volumen(e):
    return sum(p["metrado"] for p in e["partidas"] if p["clase"] == "concreto")


def _soportes(cajas, i, margen=0.02):
    """Índices de elementos cuya base apoya sobre la cara superior del elemento i (y se solapan en planta)."""
    c = cajas[i]
    arriba = (cajas[:, 2] >= c[5] - 0.35) & (cajas[:, 2] <= c[5] + 0.6)
    planta = (cajas[:, 0] < c[3] - margen) & (cajas[:, 3] > c[0] + margen) & (cajas[:, 1] < c[4] - margen) & (cajas[:, 4] > c[1] + margen)
    s = np.flatnonzero(arriba & planta)
    return s[s != i]


def comparar(nube, tol=TOL, alinear=True):
    t0 = time.time()
    ref = referencia()
    ids, cajas = ref["ids"], ref["cajas"]
    nube = np.asarray(nube, float)
    if len(nube) < 1000:
        raise ValueError(f"La nube tiene solo {len(nube)} puntos")
    nube = nube_io.submuestrear(nube, 0.04)
    alin = {"aplicada": False}
    if alinear:
        T, rmse, frac = icp(nube_io.submuestrear(nube, 0.30), nube_io.submuestrear(ref["P"], 0.15))
        nube = aplicar(T, nube)
        ang = float(np.degrees(np.arctan2(T[1, 0], T[0, 0])))
        alin = {"aplicada": True, "T": np.round(T, 6).tolist(), "traslacion_m": np.round(T[:3, 3], 3).tolist(),
                "giro_z_grados": round(ang, 3), "rmse_m": round(rmse or 0, 4), "fraccion_emparejada": round(frac, 3),
                "confiable": bool(frac >= 0.25),
                "aviso": None if frac >= 0.25 else ("Poca estructura en común con el modelo (p. ej. solo excavación y sótanos): "
                                                    "la alineación automática puede desviarse. Usa puntos de control en ejes del proyecto.")}
    d, _ = cKDTree(nube).query(ref["P"], distance_upper_bound=tol)
    toca = np.isfinite(d)
    # Visibilidad contra lo que REALMENTE hay (la nube), no contra el modelo completo: un elemento de un piso que aún
    # no existe no tapa a nada. Lo que no tiene puntos delante y tampoco tiene puntos encima, no está construido.
    cams, c = camaras(ref["P"].min(0), ref["P"].max(0))
    vis = visibilidad(ref["P"], cams, c, ESPACIADO_REF, ocluyentes=nube_io.submuestrear(nube, 0.06))
    n = len(ids)
    dueno, propio = ref["dueno"], ref["propio"]
    n_todos = np.bincount(dueno, minlength=n)
    # la cobertura se mide solo sobre los puntos PROPIOS de cada elemento (ver referencia())
    n_ref = np.bincount(dueno, weights=propio, minlength=n)
    n_vis = np.bincount(dueno, weights=vis & propio, minlength=n)
    n_toca = np.bincount(dueno, weights=toca & propio, minlength=n)
    n_toca_vis = np.bincount(dueno, weights=toca & vis & propio, minlength=n)

    cob_total = n_toca / np.maximum(n_ref, 1)
    cob_vis = np.where(n_vis > 0, n_toca_vis / np.maximum(n_vis, 1), 0.0)
    estado = np.full(n, "no_construido", dtype=object)
    frac_vis = n_vis / np.maximum(n_ref, 1)
    juzgable = (n_vis >= MIN_VISIBLES) & (frac_vis >= MIN_FRACCION_VISIBLE)
    estado[~juzgable] = "no_observable"
    estado[juzgable & (cob_vis >= COB_DUDOSO)] = "dudoso"
    # cobertura total alta con poca visibilidad prevista = el dron vio más de lo que el modelo completo dejaría ver
    # (lo de arriba aún no existe): también cuenta como construido
    estado[(juzgable & (cob_vis >= COB_CONSTRUIDO)) | ((cob_total >= COB_TOTAL_CONSTRUIDO) & (frac_vis < 0.5) & (n_ref >= MIN_VISIBLES))] = "construido"
    embebido = n_ref < np.maximum(MIN_VISIBLES, 0.1 * n_todos)     # casi todo el elemento está pegado/dentro de otro

    # Secuencia constructiva: lo que soporta a algo construido también está construido (aunque no se vea)
    soportes = {i: _soportes(cajas, i) for i in range(n)}
    motivo = {}
    cambio = True
    while cambio:
        cambio = False
        for i in range(n):
            # se infiere lo que el dron no puede juzgar; un "dudoso" que se ve bien no se infiere (lo decide una persona)
            if estado[i] == "no_observable" or (estado[i] == "dudoso" and frac_vis[i] < 0.5):
                s = [j for j in soportes[i] if estado[j] in ("construido", "inferido")]
                h = ref["anfitrion"].get(i)
                if embebido[i] and h is not None and estado[h] in ("construido", "inferido"):
                    s = [h] + s                                 # se vacía junto con el elemento que lo contiene
                if s:
                    estado[i] = "inferido"
                    motivo[i] = int(ids[s[0]])
                    cambio = True

    E = D.elementos()
    filas = []
    for i, eid in enumerate(ids):
        e = E[eid]
        filas.append({"id": eid, "grupo": e["grupo"], "nivel": e["nivel"], "paquete": e["paquete"], "sector": e["sector"],
                      "estado": estado[i], "cobertura_visible": round(float(cob_vis[i]), 3), "cobertura_total": round(float(cob_total[i]), 3),
                      "visible": round(float(frac_vis[i]), 3), "puntos_ref": int(n_todos[i]), "puntos_propios": int(n_ref[i]),
                      "concreto_m3": round(_volumen(e), 4), "soportado_por": motivo.get(i)})

    # Alertas de secuencia: construido sobre algo que se ve claramente ausente
    alertas_sec = []
    for i in range(n):
        if estado[i] != "construido":
            continue
        debajo = [j for j in range(n) if i in soportes[j] and estado[j] == "no_construido" and n_vis[j] >= 3 * MIN_VISIBLES]
        if debajo:
            alertas_sec.append({"id": int(ids[i]), "sin_soporte_visible": [int(ids[j]) for j in debajo[:5]]})

    return {"elementos": filas, "alineacion": alin, "alertas_secuencia": alertas_sec,
            "parametros": {"tolerancia_m": tol, "espaciado_referencia_m": ESPACIADO_REF, "cobertura_construido": COB_CONSTRUIDO,
                           "cobertura_total_construido": COB_TOTAL_CONSTRUIDO, "cobertura_dudoso": COB_DUDOSO,
                           "min_puntos_visibles": MIN_VISIBLES, "min_fraccion_visible": MIN_FRACCION_VISIBLE, "puntos_nube": int(len(nube))},
            "segundos": round(time.time() - t0, 1)}


# ---------------------------------------------------------------- cruce con registros y propuesta
def proponer(comp, fecha):
    E, part = D.elementos(), D.partidas()
    ej = D.ejecutado_por_elemento()
    registros, inferidos, alertas = [], [], []
    for f in comp["elementos"]:
        e = E[f["id"]]
        hecho = ej.get(f["id"], {})
        conc = [p for p in e["partidas"] if p["clase"] == "concreto"]
        registrado = bool(conc) and all(hecho.get(p["item"], 0) >= 0.99 * p["metrado"] for p in conc)
        f["registrado"] = registrado
        if f["estado"] in ("construido", "inferido") and not registrado:
            destino = registros if f["estado"] == "construido" else inferidos
            for p in e["partidas"]:
                saldo = round(p["metrado"] - hecho.get(p["item"], 0.0), 6)
                if saldo > 1e-9:
                    destino.append({"id": f["id"], "item": p["item"], "cantidad": saldo})
        if registrado and f["estado"] in ("no_construido", "dudoso"):
            monto = sum(hecho.get(p["item"], 0.0) * part[p["item"]]["pu"] for p in e["partidas"] if p["item"] in part)
            alta = f["estado"] == "no_construido"
            alertas.append({"id": f["id"], "grupo": f["grupo"], "nivel": f["nivel"], "estado": f["estado"],
                            "severidad": "alta" if alta else "media", "cobertura_visible": f["cobertura_visible"],
                            "visible": f["visible"], "monto_registrado": round(monto, 2),
                            "texto": (f"Registrado como vaciado pero el dron {'no lo ve' if alta else 'lo ve solo en parte'}: "
                                      f"{NOMBRES_GRUPO.get(f['grupo'], f['grupo'])} {f['id']} ({f['nivel']}), "
                                      f"{f['visible']*100:.0f} % visible y {f['cobertura_visible']*100:.0f} % cubierto por la nube")})

    def resumir(regs, origen):
        grupos = {}
        for r in regs:
            e = E[r["id"]]
            g = grupos.setdefault((e["nivel"], e["grupo"]), {"nivel": e["nivel"], "grupo": e["grupo"], "nombre_grupo": NOMBRES_GRUPO.get(e["grupo"], e["grupo"]),
                                                            "origen": origen, "elementos": set(), "por_item": {}})
            g["elementos"].add(r["id"])
            g["por_item"][r["item"]] = g["por_item"].get(r["item"], 0.0) + r["cantidad"]
        out = []
        for g in sorted(grupos.values(), key=lambda x: (x["nivel"], x["grupo"])):
            out.append({**{k: v for k, v in g.items() if k not in ("elementos", "por_item")}, "n_elementos": len(g["elementos"]),
                        "elementos": sorted(g["elementos"]),
                        "partidas": [{"item": i, "desc": part[i]["desc"], "und": part[i]["und"], "cantidad": round(q, 4),
                                      "monto": round(q * part[i]["pu"], 2)} for i, q in sorted(g["por_item"].items()) if i in part]})
        return out

    res_m, res_i = resumir(registros, "medido por el dron"), resumir(inferidos, "inferido por secuencia constructiva")
    return {"fecha": fecha, "registros": registros, "registros_inferidos": inferidos, "resumen": res_m, "resumen_inferidos": res_i,
            "monto_total": round(sum(p["monto"] for r in res_m for p in r["partidas"]), 2),
            "monto_inferidos": round(sum(p["monto"] for r in res_i for p in r["partidas"]), 2),
            "alertas_valorizacion": sorted(alertas, key=lambda a: (a["severidad"] != "alta", -a["monto_registrado"])), "problemas": []}


def avance(comp):
    """Avance físico por volumen de concreto, total y por nivel."""
    niveles = {}
    tot = {"total_m3": 0.0, "construido_m3": 0.0}
    for f in comp["elementos"]:
        n = niveles.setdefault(f["nivel"], {"nivel": f["nivel"], **{s: 0 for s in ESTADOS}, "total_m3": 0.0, "construido_m3": 0.0})
        n[f["estado"]] += 1
        n["total_m3"] += f["concreto_m3"]; tot["total_m3"] += f["concreto_m3"]
        if f["estado"] in ("construido", "inferido"):
            n["construido_m3"] += f["concreto_m3"]; tot["construido_m3"] += f["concreto_m3"]
    cotas = {x["nombre"]: x["cota"] for x in D.datos_base()["niveles"]}
    filas = sorted(niveles.values(), key=lambda x: cotas.get(x["nivel"], 0))
    for x in filas + [tot]:
        x["avance_pct"] = round(100 * x["construido_m3"] / x["total_m3"], 1) if x["total_m3"] else 0.0
        x["total_m3"], x["construido_m3"] = round(x["total_m3"], 2), round(x["construido_m3"], 2)
    conteo = {s: sum(f["estado"] == s for f in comp["elementos"]) for s in ESTADOS}
    return {"total": tot, "por_nivel": filas, "conteo": conteo}


def metricas(comp, verdad):
    """Contra un escaneo con verdad conocida (sintético): ¿acierta qué está construido?"""
    gt = set(verdad["construidos"])
    tp = fp = fn = tn = 0
    sin_decidir = {"construido": 0, "no_construido": 0}
    errores = []
    for f in comp["elementos"]:
        real = f["id"] in gt
        if f["estado"] in ("no_observable", "dudoso"):
            sin_decidir["construido" if real else "no_construido"] += 1
            continue
        pred = f["estado"] in ("construido", "inferido")
        tp += pred and real; fp += pred and not real; fn += (not pred) and real; tn += (not pred) and (not real)
        if pred != real:
            errores.append({"id": f["id"], "grupo": f["grupo"], "nivel": f["nivel"], "real": "construido" if real else "no construido",
                            "estado": f["estado"], "cobertura_visible": f["cobertura_visible"], "visible": f["visible"]})
    decididos = tp + fp + fn + tn
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    out = {"elementos": len(comp["elementos"]), "decididos": decididos, "sin_decidir": sin_decidir,
           "exactitud": round((tp + tn) / decididos, 4) if decididos else None, "precision_construido": round(p, 4),
           "exhaustividad_construido": round(r, 4), "f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
           "matriz": {"vp": tp, "fp": fp, "fn": fn, "vn": tn}, "errores": errores[:30]}
    if verdad.get("falsos_registrados") is not None:
        al = set(comp.get("_alertas_ids", []))
        fr = set(verdad["falsos_registrados"])
        # una alerta es correcta si el elemento NO está construido en la verdad (sembrado o no)
        out["alertas_valorizacion"] = {"sembradas": len(fr), "detectadas": len(fr & al), "total": len(al),
                                       "correctas": len(al - gt), "falsas_alarmas": len(al & gt),
                                       "no_detectadas": sorted(fr - al)}
    if verdad.get("T_aplicada") and comp["alineacion"].get("aplicada"):
        Tv, Te = np.array(verdad["T_aplicada"]), np.array(comp["alineacion"]["T"])
        resid = Te @ Tv                                        # ideal: identidad
        out["error_alineacion"] = {"traslacion_m": round(float(np.linalg.norm(resid[:3, 3])), 4),
                                   "giro_grados": round(float(np.degrees(np.arccos(np.clip((np.trace(resid[:3, :3]) - 1) / 2, -1, 1)))), 4)}
    return out


def guardar_vista(nube, rgb, comp, max_puntos=700_000):
    """Nube alineada y submuestreada para el visor 3D: color real + distancia al modelo + estado del elemento más cercano."""
    vox = 0.05
    idx = nube_io.indices_voxel(nube, vox)
    while len(idx) > max_puntos:
        vox *= 1.25
        idx = nube_io.indices_voxel(nube, vox)
    xyz = nube[idx]
    ref = referencia()
    d, j = cKDTree(ref["P"]).query(xyz, distance_upper_bound=1.0)
    estado_el = np.array([ESTADOS.index(f["estado"]) for f in comp["elementos"]], np.uint8)
    cod = np.where(np.isfinite(d) & (d < comp["parametros"]["tolerancia_m"]), estado_el[ref["dueno"][np.minimum(j, len(ref["P"]) - 1)]], len(ESTADOS)).astype(np.uint8)
    dist = np.where(np.isfinite(d), np.minimum(d * 100, 254), 255).astype(np.uint8)
    if rgb is None:                                   # sin color: gris por altura
        g = ((xyz[:, 2] - xyz[:, 2].min()) / max(np.ptp(xyz[:, 2]), 1e-6) * 140 + 80).astype(np.uint8)
        col = np.c_[g, g, g]
    else:
        col = np.asarray(rgb)[idx].astype(np.uint8)
    np.savez_compressed(D.estado() / "escaneo_nube.npz", xyz=xyz.astype(np.float32), rgb=col, dist=dist, cod=cod)
    return {"puntos_vista": int(len(xyz)), "voxel_vista_m": round(vox, 3),
            "fuera_del_modelo_pct": round(100 * float((cod == len(ESTADOS)).mean()), 1)}


def vista_binaria():
    """[uint32 n][float32 xyz·n·3][uint8 rgb·n·3][uint8 dist_cm·n][uint8 estado·n]  (estado 5 = fuera del modelo)."""
    p = D.estado() / "escaneo_nube.npz"
    if not p.exists():
        raise LookupError("Todavía no hay una nube procesada para este modelo")
    z = np.load(p)
    return np.uint32(len(z["xyz"])).tobytes() + z["xyz"].tobytes() + z["rgb"].tobytes() + z["dist"].tobytes() + z["cod"].tobytes()


def vista_ply(ruta):
    z = np.load(D.estado() / "escaneo_nube.npz")
    nube_io.escribir_ply(ruta, z["xyz"], z["rgb"])


# ---------------------------------------------------------------- punto de entrada
_ultimo_sim = contextvars.ContextVar("escaneo_simulado", default=None)   # la simulación lo fija; nada va a disco


def procesar(nube, fecha=None, nombre="nube", verdad=None, alinear=True, rgb=None, guardar=True):
    """guardar=False: no escribe nada (ni vista, ni último, ni historial, ni bitácora). Lo usa la simulación."""
    fecha = fecha or date.today().isoformat()
    nube = np.asarray(nube, float)
    ref = referencia()
    from . import ifc_modelo
    nube, georref = ifc_modelo.a_modelo_si_hace_falta(nube, (ref["P"].min(0) + ref["P"].max(0)) / 2,
                                                      float(np.linalg.norm(ref["P"].max(0) - ref["P"].min(0)) / 2))
    comp = comparar(nube, alinear=alinear)
    comp["alineacion"]["georreferencia"] = georref
    if comp["alineacion"].get("aplicada"):
        nube = aplicar(np.array(comp["alineacion"]["T"]), nube)
    vista = guardar_vista(nube, rgb, comp) if guardar else {"puntos_vista": 0, "simulado": True}
    prop = proponer(comp, fecha)
    comp["_alertas_ids"] = [a["id"] for a in prop["alertas_valorizacion"]]
    out = {"ok": True, "nombre": nombre, "fecha": fecha, "version_datos": D.huellas()["version_datos"],
           "avance": avance(comp), "alineacion": comp["alineacion"], "parametros": comp["parametros"], "segundos": comp["segundos"],
           "vista": vista, "alertas_secuencia": comp["alertas_secuencia"], **prop,
           "elementos": comp["elementos"], "ids_por_estado": {s: [f["id"] for f in comp["elementos"] if f["estado"] == s] for s in ESTADOS}}
    if verdad:
        out["metricas"] = metricas(comp, verdad)
        out["verdad"] = {k: v for k, v in verdad.items() if k not in ("construidos",)}
    if not guardar:
        out["simulado"] = True
        return out
    (D.estado() / "escaneo_ultimo.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    _guardar_historial(out)
    bitacora.anotar("escaneo", nombre=nombre, fecha=fecha, puntos=comp["parametros"]["puntos_nube"],
                    conteo=out["avance"]["conteo"], avance_pct=out["avance"]["total"]["avance_pct"],
                    monto_propuesto=prop["monto_total"], alertas=len(prop["alertas_valorizacion"]),
                    alineacion=comp["alineacion"].get("rmse_m"), metricas=(out.get("metricas") or {}).get("exactitud"))
    return out


def _guardar_historial(out):
    """Resumen de cada escaneo (sin la lista de elementos) en estado/<obra>/escaneos/: curva de avance en el tiempo."""
    d = D.estado() / "escaneos"
    d.mkdir(parents=True, exist_ok=True)
    res = {"fecha": out["fecha"], "nombre": out["nombre"], "procesado": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
           "version_datos": out["version_datos"], "avance": {"total": out["avance"]["total"], "conteo": out["avance"]["conteo"]},
           "monto_propuesto": out["monto_total"], "monto_inferidos": out["monto_inferidos"],
           "alertas": [{"id": a["id"], "monto_registrado": a["monto_registrado"], "severidad": a["severidad"]} for a in out["alertas_valorizacion"]],
           "rmse_m": out["alineacion"].get("rmse_m"), "exactitud": (out.get("metricas") or {}).get("exactitud")}
    (d / f"{out['fecha']}_{datetime.now().strftime('%H%M%S%f')}.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")


def historial():
    d = D.estado() / "escaneos"
    if not d.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))]


def ultimo():
    sim = _ultimo_sim.get()
    if sim is not None:
        return sim
    p = D.estado() / "escaneo_ultimo.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def vista_ply_bytes():
    import io
    z = np.load(D.estado() / "escaneo_nube.npz") if (D.estado() / "escaneo_nube.npz").exists() else None
    if z is None:
        raise LookupError("Todavía no hay una nube procesada para este modelo")
    b = io.BytesIO()
    nube_io.escribir_ply(b, z["xyz"], z["rgb"])
    return b.getvalue()
