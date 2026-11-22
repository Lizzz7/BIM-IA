"""Bitácora de trazabilidad (JSON Lines, solo se agrega).

Cada evento de IA o decisión humana queda con: fecha, tarea, versión de datos, proveedor/modelo,
huella de la entrada, salida, verificación y quién decidió. Se puede auditar después con jq o pandas.
"""
import hashlib
import json
import threading
import time

from . import datos as D

_candado = threading.Lock()


def ruta():
    return D.estado() / "bitacora_ia.jsonl"


def huella(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


def anotar(tarea, **campos):
    m = D.actual()
    ev = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tarea": tarea, "modelo": m.id, "version": m.version,
          "version_datos": m.huellas["version_datos"], **campos}
    with _candado, open(ruta(), "a", encoding="utf-8") as f:
        f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
    return ev


def leer(ultimos=200, tarea=None):
    if not ruta().exists():
        return []
    filas = [json.loads(x) for x in ruta().read_text(encoding="utf-8").splitlines() if x.strip()]
    if tarea:
        filas = [f for f in filas if f["tarea"] == tarea]
    return filas[-ultimos:]


_dec = {}


def decisiones():
    """Última decisión humana por hallazgo: {id: {'decision', 'motivo', 'usuario', 'ts'}}.
    Se relee solo si la bitácora creció (antes: lectura completa del archivo en cada petición)."""
    p = ruta()
    firma = (str(p), p.stat().st_size if p.exists() else 0)
    c = _dec.get(str(p))
    if c and c[0] == firma:
        return c[1]
    out = {}
    for f in leer(10 ** 7, "decision"):
        out[f["hallazgo"]] = {k: f.get(k) for k in ("decision", "motivo", "usuario", "ts")}
    _dec[str(p)] = (firma, out)
    return out
