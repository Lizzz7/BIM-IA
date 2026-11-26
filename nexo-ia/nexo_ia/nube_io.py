"""Lectura y escritura de nubes de puntos sin dependencias pesadas (solo numpy).

Formatos de entrada:
  .ply   ascii o binario (el que exporta WebODM, CloudCompare, ReCap -> exportar)
  .xyz / .txt / .pts / .csv   columnas x y z [...]  (separador espacio, coma o ;)
  .las / .laz                 requiere `pip install laspy` (y `lazrs` para .laz)
El .rcp de ReCap es un índice propietario: desde ReCap exportar a .e57/.pts/.ply, o usar el .laz de WebODM.
"""
import io
import re
from pathlib import Path

import numpy as np

_PLY_TIPOS = {"char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1", "short": "i2", "int16": "i2",
              "ushort": "u2", "uint16": "u2", "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
              "float": "f4", "float32": "f4", "double": "f8", "float64": "f8"}


def leer(ruta_o_bytes, nombre=None) -> np.ndarray:
    """Devuelve un array (N,3) float64 con x, y, z en metros."""
    if isinstance(ruta_o_bytes, (str, Path)):
        nombre = nombre or str(ruta_o_bytes)
        datos = Path(ruta_o_bytes).read_bytes()
    else:
        datos = bytes(ruta_o_bytes)
    ext = Path(nombre or "nube.ply").suffix.lower()
    if ext == ".ply" or datos[:3] == b"ply":
        return _leer_ply(datos)
    if ext in (".las", ".laz"):
        try:
            import laspy
        except ImportError as ex:
            raise ValueError("Para .las/.laz instala laspy (pip install 'laspy[lazrs]') o exporta la nube a .ply") from ex
        las = laspy.read(io.BytesIO(datos))
        return np.c_[las.x, las.y, las.z].astype(float)
    if ext in (".xyz", ".txt", ".pts", ".csv", ""):
        texto = datos.decode("utf-8", "replace")
        filas = [ln for ln in texto.splitlines() if ln.strip() and not re.match(r"^\s*[A-Za-z#/]", ln)]
        if ext == ".pts" and filas and len(filas[0].split()) == 1:   # .pts de ReCap: la 1.ª línea es el conteo
            filas = filas[1:]
        arr = np.array([[float(v) for v in re.split(r"[\s,;]+", ln.strip())[:3]] for ln in filas if len(re.split(r"[\s,;]+", ln.strip())) >= 3])
        return arr.reshape(-1, 3)
    raise ValueError(f"Formato de nube no soportado: {ext} (usa .ply, .xyz, .pts, .las o .laz)")


def _leer_ply(datos: bytes) -> np.ndarray:
    fin = datos.find(b"end_header")
    if fin < 0:
        raise ValueError("PLY sin end_header")
    cab = datos[:fin].decode("ascii", "replace").splitlines()
    cuerpo = datos[fin + len("end_header"):]
    cuerpo = cuerpo[2:] if cuerpo[:2] == b"\r\n" else cuerpo[1:]
    formato = next(ln.split()[1] for ln in cab if ln.startswith("format"))
    elementos, actual = [], None
    for ln in cab:
        p = ln.split()
        if not p:
            continue
        if p[0] == "element":
            actual = {"nombre": p[1], "n": int(p[2]), "props": []}
            elementos.append(actual)
        elif p[0] == "property" and actual is not None:
            if p[1] == "list":
                actual["props"].append(("__lista__", p[2], p[3], p[4]))
            else:
                actual["props"].append((p[2], p[1]))
    vert = next((e for e in elementos if e["nombre"] == "vertex"), None)
    if vert is None:
        raise ValueError("PLY sin vértices")
    nombres = [x[0] for x in vert["props"]]
    if formato == "ascii":
        lineas = cuerpo.decode("ascii", "replace").split("\n")
        # saltar elementos anteriores a vertex (raro)
        salto = sum(e["n"] for e in elementos[:elementos.index(vert)])
        filas = [ln.split() for ln in lineas[salto:salto + vert["n"]]]
        A = np.array([[float(f[nombres.index(c)]) for c in "xyz"] for f in filas])
        return A
    if any(x[0] == "__lista__" for x in vert["props"]):
        raise ValueError("PLY binario con listas en vertex: no soportado")
    orden = "<" if "little" in formato else ">"
    dt = np.dtype([(x[0], orden + _PLY_TIPOS[x[1]]) for x in vert["props"]])
    off = 0
    for e in elementos[:elementos.index(vert)]:
        if any(x[0] == "__lista__" for x in e["props"]):
            raise ValueError("PLY binario con listas antes de vertex: no soportado")
        off += e["n"] * np.dtype([(x[0], orden + _PLY_TIPOS[x[1]]) for x in e["props"]]).itemsize
    v = np.frombuffer(cuerpo, dtype=dt, count=vert["n"], offset=off)
    return np.c_[v["x"], v["y"], v["z"]].astype(float)


def escribir_ply(ruta, xyz: np.ndarray, rgb: np.ndarray = None):
    """PLY binario little-endian; rgb opcional (N,3) uint8."""
    xyz = np.asarray(xyz, "<f4")
    cab = ["ply", "format binary_little_endian 1.0", f"element vertex {len(xyz)}",
           "property float x", "property float y", "property float z"]
    if rgb is not None:
        cab += ["property uchar red", "property uchar green", "property uchar blue"]
        dt = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")])
    else:
        dt = np.dtype([("x", "<f4"), ("y", "<f4"), ("z", "<f4")])
    a = np.empty(len(xyz), dtype=dt)
    a["x"], a["y"], a["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    if rgb is not None:
        rgb = np.asarray(rgb, "u1")
        a["r"], a["g"], a["b"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    with open(ruta, "wb") as f:
        f.write(("\n".join(cab + ["end_header"]) + "\n").encode("ascii"))
        f.write(a.tobytes())


def submuestrear(xyz: np.ndarray, voxel: float) -> np.ndarray:
    """Un punto (el primero) por vóxel de lado `voxel` m."""
    if len(xyz) == 0:
        return xyz
    k = np.floor((xyz - xyz.min(0)) / voxel).astype(np.int64)
    _, idx = np.unique(k, axis=0, return_index=True)
    return xyz[np.sort(idx)]
