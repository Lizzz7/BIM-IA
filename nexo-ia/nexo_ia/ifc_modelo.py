"""IFC del proyecto -> georreferencia + geometría para el avance por dron.

El IFC exportado de Revit viene en COORDENADAS COMPARTIDAS (E, N, cota: lo mismo que usa WebODM si los puntos de
control están en UTM). El panel trabaja en coordenadas internas del modelo. Este módulo:
  1. Cruza cada elemento IFC con el panel por su Tag (= ElementId de Revit).
  2. Calcula la transformación IFC -> panel (giro en planta + traslación) por mínimos cuadrados sobre todos los
     elementos comunes, y reporta el residuo (cuánto calza).
  3. Guarda esa georreferencia por obra: una nube en UTM/compartidas se convierte sola al subirla.
  4. Entrega las mallas del IFC (incluidos los elementos que el panel no metra: barandas, tramos de escalera,
     bovedillas, barras) para generar nubes sintéticas desde el IFC.
"""
import json
import time
from pathlib import Path

import numpy as np

from . import datos as D

_cache = {}


def _abrir(ruta):
    try:
        import ifcopenshell
        import ifcopenshell.geom
    except ImportError as ex:
        raise ValueError("Para leer IFC instala ifcopenshell (pip install ifcopenshell)") from ex
    return ifcopenshell, ifcopenshell.geom, ifcopenshell.open(str(ruta))


def mallas_ifc(ruta):
    """{guid: {"tag": int|None, "clase", "nombre", "nivel", "tri": (n,3,3) en coords del IFC}} (en caché por archivo)."""
    ruta = Path(ruta)
    k = ("mallas", str(ruta), ruta.stat().st_mtime)
    if k in _cache:
        return _cache[k]
    ifcopenshell, geom, f = _abrir(ruta)
    import ifcopenshell.util.element as ue
    s = geom.settings()
    s.set("use-world-coords", True)
    out = {}
    elementos = [e for e in f.by_type("IfcElement") if not e.is_a("IfcOpeningElement") and e.Representation]
    it = geom.iterator(s, f, include=elementos)
    if it.initialize():
        while True:
            sh = it.get()
            e = f.by_guid(sh.guid)
            v = np.asarray(sh.geometry.verts, float).reshape(-1, 3)
            fc = np.asarray(sh.geometry.faces, int).reshape(-1, 3)
            if len(fc):
                try:
                    tag = int(e.Tag)
                except (TypeError, ValueError):
                    tag = None
                cont = ue.get_container(e) or ue.get_container(ue.get_aggregate(e) or e)
                padre = ue.get_aggregate(e)                      # tramo de escalera -> su IfcStair (que es lo que metra el panel)
                try:
                    tag_padre = int(padre.Tag) if padre is not None and not padre.is_a("IfcSpatialStructureElement") else None
                except (TypeError, ValueError):
                    tag_padre = None
                out[sh.guid] = {"tag": tag, "tag_padre": tag_padre, "clase": e.is_a(), "nombre": (e.ObjectType or e.Name or "")[:80],
                                "nivel": cont.Name if cont else "-", "tri": v[fc]}
            if not it.next():
                break
    _cache[k] = out
    return out


def _centroide(T):
    a = 0.5 * np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
    return (T.mean(1) * a[:, None]).sum(0) / max(a.sum(), 1e-12)


def _por_elemento(m, ids):
    """Agrupa las mallas IFC por ElementId del panel (un elemento puede venir en varias partes)."""
    grupos, extras = {}, []
    for g in m.values():
        i = g["tag"] if g["tag"] in ids else g.get("tag_padre") if g.get("tag_padre") in ids else None
        if i is None:
            extras.append(g)
        else:
            grupos.setdefault(i, []).append(g["tri"])
    return {i: np.concatenate(v) for i, v in grupos.items()}, extras


def ajustar(ruta):
    """Transformación IFC -> panel (giro en planta + traslación) y calidad del ajuste."""
    t0 = time.time()
    m = mallas_ifc(ruta)
    tri = __import__("nexo_ia.escaneo", fromlist=["triangulos"]).triangulos()
    ids = set(tri)
    por_id, extras = _por_elemento(m, ids)
    pares = [(por_id[i].reshape(-1, 3), tri[i].reshape(-1, 3)) for i in sorted(por_id)]
    if len(pares) < 3:
        raise ValueError(f"El IFC solo comparte {len(pares)} elementos con el modelo del panel (se cruzan por ElementId/Tag). "
                         "¿Es del mismo proyecto de Revit?")
    A = np.array([_centroide(por_id[i]) for i in sorted(por_id)])    # centroide de superficie: no depende de la teselación
    B = np.array([_centroide(tri[i]) for i in sorted(por_id)])       # ni del giro (una caja alineada a ejes sí)
    usar = np.ones(len(A), bool)
    for _ in range(4):                                                 # ajuste robusto: descarta los que no calzan
        ca, cb = A[usar].mean(0), B[usar].mean(0)
        H = (A[usar] - ca)[:, :2].T @ (B[usar] - cb)[:, :2]            # giro solo en planta (norte del proyecto)
        U, _, Vt = np.linalg.svd(H)
        R2 = Vt.T @ U.T
        if np.linalg.det(R2) < 0:
            Vt[-1] *= -1
            R2 = Vt.T @ U.T
        T = np.eye(4)
        T[:2, :2] = R2
        T[:3, 3] = cb - T[:3, :3] @ ca
        res = np.linalg.norm(A @ T[:3, :3].T + T[:3, 3] - B, axis=1)
        usar = res < max(0.10, 3 * np.median(res))
    no_calzan = [int(i) for i, r in zip(sorted(por_id), res) if r >= 0.10]
    clases = {}
    for g in extras:
        clases[g["clase"]] = clases.get(g["clase"], 0) + 1
    return {"T_ifc_a_modelo": T.tolist(), "T_modelo_a_ifc": np.linalg.inv(T).tolist(),
            "giro_grados": round(float(np.degrees(np.arctan2(T[1, 0], T[0, 0]))), 4),
            "traslacion": np.round(T[:3, 3], 3).tolist(),
            "residuo_mediano_m": round(float(np.median(res)), 4), "residuo_p95_m": round(float(np.percentile(res, 95)), 4),
            "elementos_ifc": len(m), "elementos_comunes": len(pares), "elementos_panel": len(ids),
            "panel_sin_ifc": len(ids - set(por_id)), "no_calzan": no_calzan[:50], "n_no_calzan": len(no_calzan), "solo_en_ifc": clases, "segundos": round(time.time() - t0, 1)}


def cargar(datos_ifc: bytes, nombre="modelo.ifc"):
    """Guarda el IFC en el estado de la obra, calcula y guarda la georreferencia."""
    destino = D.estado() / "modelo.ifc"
    destino.write_bytes(datos_ifc)
    info = ajustar(destino)
    info.update({"archivo": Path(nombre).name, "fecha_carga": time.strftime("%Y-%m-%d %H:%M"),
                 "version_datos": D.huellas()["version_datos"]})
    (D.estado() / "georef_ifc.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return info


def georef():
    p = D.estado() / "georef_ifc.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def ruta_ifc():
    p = D.estado() / "modelo.ifc"
    return p if p.exists() else None


def mallas_en_modelo():
    """Mallas del IFC ya llevadas a coordenadas del panel: ({ElementId: tri}, [extras {clase, nombre, nivel, tri}])."""
    g, r = georef(), ruta_ifc()
    if not g or not r:
        return None, None
    T = np.array(g["T_ifc_a_modelo"])
    k = ("enmodelo", str(r), r.stat().st_mtime)
    if k not in _cache:
        ids = set(__import__("nexo_ia.escaneo", fromlist=["triangulos"]).triangulos())
        p, ex = _por_elemento(mallas_ifc(r), ids)
        por_id = {i: t @ T[:3, :3].T + T[:3, 3] for i, t in p.items()}
        extras = [{"clase": x["clase"], "nombre": x["nombre"], "nivel": x["nivel"], "tri": x["tri"] @ T[:3, :3].T + T[:3, 3]} for x in ex]
        _cache[k] = (por_id, extras)
    return _cache[k]


def a_modelo_si_hace_falta(nube, centro_modelo, radio_modelo):
    """Si la nube está lejos del modelo (UTM / coordenadas compartidas), la convierte con la georreferencia del IFC."""
    c = np.median(nube[:: max(1, len(nube) // 20000)], axis=0)
    lejos = float(np.linalg.norm(c[:2] - np.asarray(centro_modelo)[:2]))
    if lejos <= max(200.0, 5 * radio_modelo):
        return nube, None
    g = georef()
    if not g:
        raise ValueError(f"La nube está a {lejos/1000:.1f} km del modelo: parece estar en UTM o coordenadas compartidas. "
                         "Carga el IFC del proyecto (exportado de Revit con coordenadas compartidas) para convertirla.")
    T = np.array(g["T_ifc_a_modelo"])
    return nube @ T[:3, :3].T + T[:3, 3], {"origen": "georreferencia del IFC", "archivo": g.get("archivo"),
                                           "giro_grados": g["giro_grados"], "distancia_original_km": round(lejos / 1000, 2)}
