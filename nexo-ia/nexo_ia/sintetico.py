"""Nube de puntos SINTÉTICA con verdad conocida, generada desde el propio modelo de Revit.

Sirve para validar el comparador Scan-vs-BIM antes (y además) del vuelo real:
  1. Verdad: está construido lo que el cronograma programó hasta la fecha de corte, menos algunas
     ACTIVIDADES RETRASADAS al azar (un vaciado reciente que se atrasó) y todo lo que se apoya en ellas.
  2. Se siembran FALSOS REGISTRADOS: elementos con metrado registrado que en la "realidad" no existen
     (simula una valorización sin ejecución, lo que el sistema debe alertar).
  3. Puntos CON COLOR sobre lo construido (concreto más oscuro si es reciente) + terreno, excavación y vecinos
     + lo que no está en el BIM: grúa, andamio, material acopiado, encofrado, arranques de acero.
  4. Oclusión: solo queda lo que se ve desde las cámaras del plan de vuelo.
  5. Efectos de fotogrametría: menos densidad lejos de la cámara, huecos en manchas, error a lo largo del rayo,
     puntos sueltos en bordes y una desalineación leve (georreferenciado imperfecto).
Devuelve (xyz, verdad, etiqueta por punto, rgb uint8).
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

    # 3) puntos con color (lo que vería la cámara del dron)
    P, etiqueta, color = [], [], []

    def agregar(pts, et, rgb, var=0.03):
        if len(pts) == 0:
            return
        c = np.clip(np.asarray(rgb, float) + rng.normal(0, var, (len(pts), 3)) + rng.normal(0, var, (len(pts), 1)), 0, 1)
        P.append(pts); etiqueta.append(np.full(len(pts), et)); color.append(c)

    for i in sorted(construidos):
        p = muestrear_superficie(tri[i], espaciado, rng)
        edad = (corte - prog[i]).days if prog[i] else 60
        g = 0.50 + 0.17 * min(edad, 30) / 30                                 # concreto fresco más oscuro, se aclara al secar
        manchas = 0.035 * (np.sin(p[:, 0] * 1.7 + i) + np.sin(p[:, 1] * 1.3 + p[:, 2] * 0.9))[:, None]
        agregar(p, i, np.array([g, g, g * 1.02]) + manchas, 0.025)
    todos = np.vstack([tri[i].reshape(-1, 3) for i in ids])
    bmin, bmax = todos.min(0), todos.max(0)
    hecho = np.vstack([tri[i].reshape(-1, 3) for i in construidos]) if construidos else todos[:1]
    top = max(hecho[:, 2].max(), z_suelo)
    losas = [tri[i][..., 2].max() for i in construidos if E[i]["grupo"] in ("ALI", "LMA")]
    piso = max(losas) if losas else z_suelo                          # la losa construida más alta: ahí se acopia material
    if objetos_ajenos:
        agregar(_caja((bmax[0] + 7, bmin[1] - 5, z_suelo + 12), (1.4, 1.4, 24), rng, espaciado * 2), -2, (0.95, 0.76, 0.10))    # torre grúa
        agregar(_caja((bmax[0] + 7 - 9, bmin[1] - 5, z_suelo + 24), (20, 1.0, 1.0), rng, espaciado * 2), -2, (0.95, 0.76, 0.10))  # pluma
        agregar(_caja((bmin[0] - 1.6, (bmin[1] + bmax[1]) / 2, z_suelo + 3), (0.8, 10, 6), rng, espaciado * 2), -2, (0.20, 0.38, 0.72))  # andamio
        for k in range(3):                                                                                       # material sobre la losa
            tono = [(0.66, 0.30, 0.20), (0.82, 0.81, 0.78), (0.60, 0.44, 0.27)][k]                              # ladrillo, cemento, madera
            agregar(_caja((rng.uniform(bmin[0] + 2, bmax[0] - 2), rng.uniform(bmin[1] + 2, bmax[1] - 2), piso + 0.5),
                          (rng.uniform(0.8, 2.0), rng.uniform(0.8, 2.0), 1.0), rng, espaciado * 1.5), -2, tono)
        for i in sorted(retr):          # encofrado (tablero + soleras ≈ 18 cm) alrededor de columnas y placas retrasadas
            if E[i]["grupo"] in ("COL", "PLA"):
                v = tri[i].reshape(-1, 3); mn, mx = v.min(0), v.max(0)
                agregar(_caja((mn + mx) / 2, (mx - mn) + [0.36, 0.36, -0.3], rng, espaciado * 1.5), -2, (0.62, 0.45, 0.28))
        # arranques de acero sobre columnas y placas construidas cuyo tramo superior aún no existe
        for i in sorted(construidos):
            if E[i]["grupo"] not in ("COL", "PLA"):
                continue
            arriba = [ids[j] for j in _soportes(cajas, pos[i]) if E[ids[j]]["grupo"] in ("COL", "PLA")]
            if not arriba or any(a in construidos for a in arriba):
                continue
            v = tri[i].reshape(-1, 3); mn, mx = v.min(0), v.max(0)
            xs, ys = np.linspace(mn[0] + 0.05, mx[0] - 0.05, max(2, int((mx[0] - mn[0]) / 0.2))), np.linspace(mn[1] + 0.05, mx[1] - 0.05, max(2, int((mx[1] - mn[1]) / 0.2)))
            barras = [(x, y) for x in xs for y in ys if x in (xs[0], xs[-1]) or y in (ys[0], ys[-1])]
            zz = np.arange(mx[2], mx[2] + 0.9, 0.025)
            agregar(np.array([(x + rng.normal(0, 0.005), y + rng.normal(0, 0.005), z) for x, y in barras for z in zz]), -2, (0.45, 0.26, 0.16), 0.04)
        # vecinos (medianeras de sillar) a ambos lados
        for lado, alto in ((-1, 9.0), (1, 6.0)):
            yc = (bmin[1] - 7.5) if lado < 0 else (bmax[1] + 7.5)
            agregar(_caja(((bmin[0] + bmax[0]) / 2, yc, z_suelo + alto / 2), (bmax[0] - bmin[0] + 6, 12, alto), rng, espaciado * 3), -3, (0.88, 0.85, 0.77), 0.05)
    # terreno (fuera de la excavación) + excavación: cortes de suelo y fondo
    gx = np.arange(bmin[0] - 15, bmax[0] + 15, espaciado * 4)
    gy = np.arange(bmin[1] - 15, bmax[1] + 15, espaciado * 4)
    G = np.stack(np.meshgrid(gx, gy), -1).reshape(-1, 2)
    G = G + rng.uniform(-espaciado * 2, espaciado * 2, G.shape)                  # sin patrón de grilla
    m = 0.3
    fuera = (G[:, 0] < bmin[0] - m) | (G[:, 0] > bmax[0] + m) | (G[:, 1] < bmin[1] - m) | (G[:, 1] > bmax[1] + m)
    vecino = (G[:, 1] < bmin[1] - 1.5) | (G[:, 1] > bmax[1] + 1.5)
    G = G[fuera & ~(vecino & (np.abs(G[:, 0] - (bmin[0] + bmax[0]) / 2) < (bmax[0] - bmin[0]) / 2 + 3))]
    agregar(np.c_[G, rng.normal(z_suelo, 0.03, len(G))], -1, (0.74, 0.64, 0.50), 0.04)
    fondo = np.stack(np.meshgrid(np.arange(bmin[0] - m, bmax[0] + m, espaciado * 3), np.arange(bmin[1] - m, bmax[1] + m, espaciado * 3)), -1).reshape(-1, 2)
    fondo = fondo + rng.uniform(-espaciado * 1.5, espaciado * 1.5, fondo.shape)
    agregar(np.c_[fondo, rng.normal(bmin[2] - 0.05, 0.03, len(fondo))], -1, (0.58, 0.50, 0.40), 0.04)
    for eje, val in ((0, bmin[0] - m), (0, bmax[0] + m), (1, bmin[1] - m), (1, bmax[1] + m)):
        otro = 1 - eje
        a = np.arange(bmin[otro] - m, bmax[otro] + m, espaciado * 3); z = np.arange(bmin[2], z_suelo, espaciado * 3)
        A = np.stack(np.meshgrid(a, z), -1).reshape(-1, 2) + rng.uniform(-espaciado * 1.5, espaciado * 1.5, (len(a) * len(z), 2))
        Q = np.empty((len(A), 3)); Q[:, eje] = val + rng.normal(0, 0.04, len(A)); Q[:, otro] = A[:, 0]; Q[:, 2] = A[:, 1]
        agregar(Q, -1, (0.70, 0.60, 0.46), 0.05)
    P, L, C = np.vstack(P), np.concatenate(etiqueta), np.vstack(color)
    n0 = len(P)

    # 4) oclusión desde el plan de vuelo (el dron vuela sobre lo construido, no sobre el modelo completo)
    cams, c = camaras(bmin, np.r_[bmax[:2], top], z_suelo)
    if oclusion:
        v = visibilidad(P, cams, c, espaciado)
        P, L, C = P[v], L[v], C[v]

    # 5) efectos de la fotogrametría
    dcam, cerca = np.full(len(P), np.inf), np.zeros(len(P), int)
    for k, cm in enumerate(cams):
        d = np.linalg.norm(P - cm, axis=1); f = d < dcam; dcam[f], cerca[f] = d[f], k
    keep = rng.random(len(P)) < np.clip((22 / dcam) ** 2, 0.3, 1.0)                     # menos densidad lejos de la cámara
    vox = np.floor(P / 1.5).astype(np.int64)                                            # huecos en manchas (superficies lisas, sombras)
    h = (vox[:, 0] * 73856093) ^ (vox[:, 1] * 19349663) ^ (vox[:, 2] * 83492791)
    r_vox = (np.abs(h) % 1000) / 1000.0
    keep &= rng.random(len(P)) > np.clip(huecos * 2 * r_vox, 0, 0.95)
    P, L, C, dcam, cerca = P[keep], L[keep], C[keep], dcam[keep], cerca[keep]
    rayo = (P - cams[cerca]) / dcam[:, None]
    sig = ruido * np.clip(dcam / 25, 0.6, 2.5)
    P = P + rayo * rng.normal(0, 1, len(P))[:, None] * sig[:, None] + rng.normal(0, ruido * 0.35, P.shape)   # el error va sobre el rayo
    atip = rng.random(len(P)) < 0.003                                                   # puntos "volando" en bordes
    P[atip] += rng.normal(0, 0.25, (atip.sum(), 3))
    C = np.clip(C + rng.normal(0, 0.02, C.shape), 0, 1)
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
    return P, verdad, L, (C * 255).astype(np.uint8)
