"""Nube de puntos SINTÉTICA con verdad conocida, generada desde el propio modelo de Revit.

Sirve para validar el comparador Scan-vs-BIM antes (y además) del vuelo real:
  1. Verdad: está construido lo que el cronograma programó hasta la fecha de corte, menos algunas
     ACTIVIDADES RETRASADAS al azar (un vaciado reciente que se atrasó) y todo lo que se apoya en ellas.
  2. Se siembran FALSOS REGISTRADOS: elementos con metrado registrado que en la "realidad" no existen
     (simula una valorización sin ejecución, lo que el sistema debe alertar).
  3. Puntos sobre lo construido + terreno + objetos que no están en el BIM (grúa, andamio, materiales,
     encofrado alrededor de columnas retrasadas).
  4. Oclusión: solo queda lo que se ve desde las cámaras del plan de vuelo.
  5. Ruido de fotogrametría, huecos y una desalineación leve (georreferenciado imperfecto).
"""
from datetime import date, datetime

import numpy as np

from . import datos as D
from .escaneo import _soportes, camaras, muestrear_superficie, triangulos, visibilidad


HORIZONTALES = {"VIG", "VCH", "ALI", "LMA", "ESC", "RAM"}


def _fecha(s):
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except (TypeError, ValueError):
            pass
    return None


def _caja(c, dims, rng, espaciado):
    """Puntos sobre la superficie de una caja."""
    c, h = np.asarray(c, float), np.asarray(dims, float) / 2
    caras = []
    for eje in range(3):
        for s in (-1, 1):
            o = [i for i in range(3) if i != eje]
            n = max(int(4 * h[o[0]] * h[o[1]] / espaciado ** 2), 4)
            p = np.empty((n, 3))
            p[:, eje] = c[eje] + s * h[eje]
            p[:, o[0]] = c[o[0]] + rng.uniform(-h[o[0]], h[o[0]], n)
            p[:, o[1]] = c[o[1]] + rng.uniform(-h[o[1]], h[o[1]], n)
            caras.append(p)
    return np.vstack(caras)


def generar(fecha_corte, semilla=7, retrasados=0.08, ventana_dias=45, falsos_registrados=2, espaciado=0.07,
            ruido=0.02, huecos=0.15, desalinear=True, oclusion=True, objetos_ajenos=True, z_suelo=0.0):
    rng = np.random.default_rng(semilla)
    corte = _fecha(fecha_corte) if isinstance(fecha_corte, str) else fecha_corte or date.today()
    E, tri = D.elementos(), triangulos()
    ids = sorted(tri)

    # 1) verdad según el cronograma
    cajas = np.array([np.r_[tri[i].reshape(-1, 3).min(0), tri[i].reshape(-1, 3).max(0)] for i in ids])
    pos = {i: k for k, i in enumerate(ids)}

    def con_lo_de_arriba(semilla_ids):
        """Si algo no se construyó, tampoco lo que se apoya en él (cierre transitivo hacia arriba)."""
        fuera, pila = set(semilla_ids), list(semilla_ids)
        while pila:
            for j in _soportes(cajas, pos[pila.pop()]):
                if ids[j] not in fuera:
                    fuera.add(ids[j]); pila.append(ids[j])
        return fuera

    prog = {i: _fecha(E[i].get("fecha_prog")) for i in ids}
    construidos = {i for i in ids if prog[i] and prog[i] <= corte}
    acts = sorted({E[i]["actividad"] for i in construidos if (corte - prog[i]).days <= ventana_dias and E[i].get("actividad")})
    n_act = int(round(len(acts) * retrasados)) if retrasados else 0
    n_act = max(n_act, 1) if retrasados and len(acts) >= 4 else n_act
    act_retr = set(rng.choice(acts, n_act, replace=False).tolist()) if n_act else set()
    semilla_r = {i for i in construidos if E[i].get("actividad") in act_retr}
    # un techo se vacía de una vez por sector: si se atrasa una parte horizontal, se atrasa todo ese vaciado
    techos = {(E[i]["nivel"], E[i]["sector"]) for i in semilla_r if E[i]["grupo"] in HORIZONTALES}
    semilla_r |= {i for i in construidos if E[i]["grupo"] in HORIZONTALES and (E[i]["nivel"], E[i]["sector"]) in techos}
    retr = con_lo_de_arriba(sorted(semilla_r)) & construidos
    construidos -= retr

    # 2) falsos registrados: con concreto registrado completo pero no existen (y nada construido encima)
    ej = D.ejecutado_por_elemento()
    regs = [i for i in sorted(construidos) if any(p["clase"] == "concreto" and ej.get(i, {}).get(p["item"], 0) >= 0.99 * p["metrado"]
                                                 for p in E[i]["partidas"])]
    regs = [i for i in regs if not (con_lo_de_arriba([i]) - {i}) & construidos]
    falsos = set(rng.choice(regs, min(falsos_registrados, len(regs)), replace=False).tolist()) if regs and falsos_registrados else set()
    construidos -= falsos

    # 3) puntos
    P, etiqueta = [], []
    for i in sorted(construidos):
        p = muestrear_superficie(tri[i], espaciado, rng)
        P.append(p); etiqueta.append(np.full(len(p), i))
    todos = np.vstack([tri[i].reshape(-1, 3) for i in ids])
    bmin, bmax = todos.min(0), todos.max(0)
    hecho = np.vstack([tri[i].reshape(-1, 3) for i in construidos]) if construidos else todos[:1]
    top = max(hecho[:, 2].max(), z_suelo)
    losas = [tri[i][..., 2].max() for i in construidos if E[i]["grupo"] in ("ALI", "LMA")]
    piso = max(losas) if losas else z_suelo                          # la losa construida más alta: ahí se acopia material
    ajenos = []
    if objetos_ajenos:
        ajenos.append(_caja((bmax[0] + 7, bmin[1] - 5, z_suelo + 12), (1.4, 1.4, 24), rng, espaciado * 2))            # torre grúa
        ajenos.append(_caja((bmin[0] - 1.6, (bmin[1] + bmax[1]) / 2, z_suelo + 3), (0.8, 10, 6), rng, espaciado * 2))  # andamio
        for _ in range(3):                                                                                              # material sobre la losa
            ajenos.append(_caja((rng.uniform(bmin[0] + 2, bmax[0] - 2), rng.uniform(bmin[1] + 2, bmax[1] - 2), piso + 0.5),
                                (rng.uniform(0.8, 2.0), rng.uniform(0.8, 2.0), 1.0), rng, espaciado * 1.5))
        for i in sorted(retr):          # encofrado (tablero + soleras ≈ 18 cm) alrededor de columnas y placas retrasadas
            if E[i]["grupo"] in ("COL", "PLA"):
                v = tri[i].reshape(-1, 3); mn, mx = v.min(0), v.max(0)
                ajenos.append(_caja((mn + mx) / 2, (mx - mn) + [0.36, 0.36, -0.3], rng, espaciado * 1.5))
    for a in ajenos:
        P.append(a); etiqueta.append(np.full(len(a), -2))
    gx = np.arange(bmin[0] - 15, bmax[0] + 15, espaciado * 4)
    gy = np.arange(bmin[1] - 15, bmax[1] + 15, espaciado * 4)
    G = np.stack(np.meshgrid(gx, gy), -1).reshape(-1, 2)
    fuera = (G[:, 0] < bmin[0] - 0.5) | (G[:, 0] > bmax[0] + 0.5) | (G[:, 1] < bmin[1] - 0.5) | (G[:, 1] > bmax[1] + 0.5)
    G = np.c_[G[fuera], rng.normal(z_suelo, 0.03, fuera.sum())]
    P.append(G); etiqueta.append(np.full(len(G), -1))
    P, L = np.vstack(P), np.concatenate(etiqueta)
    n0 = len(P)

    # 4) oclusión desde el plan de vuelo (el dron vuela sobre lo construido, no sobre el modelo completo)
    if oclusion:
        cams, c = camaras(bmin, np.r_[bmax[:2], top], z_suelo)
        v = visibilidad(P, cams, c, espaciado)
        P, L = P[v], L[v]

    # 5) huecos, ruido y desalineación
    k = rng.random(len(P)) > huecos
    P, L = P[k], L[k]
    P = P + rng.normal(0, ruido, P.shape)
    T = np.eye(4)
    if desalinear:
        a = np.radians(rng.uniform(-0.8, 0.8))
        T[:3, :3] = [[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]]
        T[:3, 3] = rng.uniform(-0.3, 0.3, 3) * [1, 1, 0.3]
        P = P @ T[:3, :3].T + T[:3, 3]

    puntos_por_el = {int(i): int(n) for i, n in zip(*np.unique(L[L >= 0], return_counts=True))}
    verdad = {"fecha_corte": corte.isoformat(), "semilla": semilla, "construidos": sorted(int(i) for i in construidos),
              "retrasados": sorted(int(i) for i in retr), "actividades_retrasadas": sorted(act_retr), "falsos_registrados": sorted(int(i) for i in falsos),
              "construidos_invisibles": sorted(int(i) for i in construidos if puntos_por_el.get(i, 0) < 10),
              "T_aplicada": T.tolist(), "ruido_m": ruido, "huecos": huecos, "espaciado_m": espaciado,
              "puntos_antes_oclusion": int(n0), "puntos": int(len(P)), "oclusion": oclusion}
    return P, verdad, L
