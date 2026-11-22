"""Modelos BIM publicados (solo lectura) + estado de obra por modelo.

Conceptos
---------
- MODELO: una obra/especialidad (p. ej. REP0-MOD2). Tiene VERSIONES publicadas desde Revit.
- VERSIÓN: carpeta inmutable  modelos/<modelo>/<version>/  con un manifiesto modelo.json y los archivos que
  exporta el complemento. Nunca se modifica: una corrección en Revit = una versión nueva.
- ESTADO del modelo: lo que cambia en obra (registros de metrado, bitácora, decisiones, caché) en
  estado/<modelo>/. Es compartido por todas las versiones del modelo (el avance sigue al elemento, no a la versión).

Fuentes de modelos (se combinan):
  1. NEXO_MODELOS (def. nexo-ia/modelos): carpetas publicadas (subidas por zip o copiadas).
  2. NEXO_REPO (def. ../BIM-IA): el repo del equipo se registra como un modelo más, en solo lectura.

El modelo activo de cada petición se fija con usar(id) (contextvar: seguro con varios hilos).
"""
import contextvars
import hashlib
import json
import os
import re
import shutil
import threading
from functools import cached_property
from pathlib import Path

AQUI = Path(__file__).resolve().parent.parent
# El repo puede estar AL LADO (./BIM-IA y ./nexo-ia) o nexo-ia puede estar DENTRO del repo (BIM-IA/nexo-ia)
_REPO_DEF = AQUI.parent if (AQUI.parent / "1_Panel").exists() else AQUI.parent / "BIM-IA"
REPO = Path(os.environ.get("NEXO_REPO", _REPO_DEF)).resolve()
MODELOS = Path(os.environ.get("NEXO_MODELOS", AQUI / "modelos")).resolve()
ESTADO = Path(os.environ.get("NEXO_ESTADO", AQUI / "estado")).resolve()
MODELO_REPO = os.environ.get("NEXO_MODELO", "REP0-MOD2-R02")
PANEL = Path(os.environ.get("NEXO_PANEL", REPO / "1_Panel" / "index.html")).resolve()

CLAVES = ["instantanea", "cronograma", "metrados", "auditoria", "parametros", "presupuesto"]
OPCIONALES = {"presupuesto", "registros_iniciales"}


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


class Modelo:
    """Una versión publicada de un modelo. Todo lo que lee se guarda en memoria (cached_property)."""

    def __init__(self, id, version, archivos, nombre=None, publicado=None, origen=""):
        self.id, self.version, self.nombre = id, version, nombre or id
        self.publicado, self.origen = publicado, origen
        self.F = {k: Path(v) for k, v in archivos.items()}

    # ------------------------------------------------ identidad y verificación
    def faltantes(self):
        return [k for k in CLAVES if k not in OPCIONALES and not (k in self.F and self.F[k].exists())]

    @cached_property
    def huellas(self):
        h = {k: _sha(self.F[k])[:12] for k in CLAVES if k in self.F and self.F[k].exists()}
        h["version_datos"] = hashlib.sha256("".join(h[k] for k in sorted(h)).encode()).hexdigest()[:12]
        return h

    def resumen(self):
        return {"id": self.id, "version": self.version, "nombre": self.nombre, "publicado": self.publicado,
                "origen": self.origen, "version_datos": self.huellas["version_datos"]}

    @property
    def estado(self) -> Path:
        d = ESTADO / self.id
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------ datos de la versión
    @cached_property
    def instantanea(self):
        cache = self.estado / "cache"
        cache.mkdir(parents=True, exist_ok=True)
        marca = cache / f"instantanea_{self.huellas['instantanea']}.json"
        if not marca.exists():
            html = self.F["instantanea"].read_text(encoding="utf-8")
            m = re.search(r"window\.NEXO_SNAPSHOT=(\{.*?\});</script>", html, re.S)
            if not m:
                raise ValueError(f"{self.F['instantanea']} no contiene window.NEXO_SNAPSHOT")
            snap = json.loads(m.group(1))
            for e in snap["datos"]["elementos"]:          # los registros viven en el estado, no en la versión
                e["registro"], e["obs"] = "", ""
            snap["datos"]["registroGlobal"] = ""
            tmp = marca.with_suffix(f".{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            tmp.replace(marca)
        return json.loads(marca.read_text(encoding="utf-8"))

    @cached_property
    def geometria_bytes(self):
        return json.dumps(self.instantanea["geo"], separators=(",", ":")).encode("utf-8")

    @cached_property
    def cronograma(self):
        return json.loads(self.F["cronograma"].read_text(encoding="utf-8"))

    @cached_property
    def metrados_modelo(self):
        return {e["id"]: e for e in json.loads(self.F["metrados"].read_text(encoding="utf-8"))["elementos"]}

    @cached_property
    def auditoria_modelo(self):
        return json.loads(self.F["auditoria"].read_text(encoding="utf-8"))

    @cached_property
    def actividades_por_elemento(self):
        pr = json.loads(self.F["parametros"].read_text(encoding="utf-8"))
        return {e["id"]: {"concreto": e["actividad"], "acero": e["act_acero"], "encofrado": e["act_encofrado"]} for e in pr["elementos"]}

    @cached_property
    def apu(self):
        """APU del Excel con la función del propio repo (solo lectura); {} si no hay Excel u openpyxl."""
        if "presupuesto" not in self.F or not self.F["presupuesto"].exists():
            return {}
        import sys
        if str(REPO / "4_Python") not in sys.path:
            sys.path.insert(0, str(REPO / "4_Python"))
        try:
            from cronograma_nexo import leer_presupuesto
            return leer_presupuesto(self.F["presupuesto"])[3]
        except Exception:  # noqa: BLE001
            return {}

    @cached_property
    def partidas(self):
        return {p["item"]: p for p in self.instantanea["datos"]["partidas"]}

    @cached_property
    def elementos(self):
        return {e["id"]: e for e in self.instantanea["datos"]["elementos"] if e.get("existe", True)}

    # ------------------------------------------------ estado de obra (lectura/escritura, fuera del repo)
    def ruta_registros(self) -> Path:
        r = self.estado / "registros.json"
        if not r.exists():
            ini = self.F.get("registros_iniciales")
            if ini and ini.exists():
                shutil.copy(ini, r)                       # copia: la versión publicada no se toca
            else:
                r.write_text('{"elementos":{},"global":""}', encoding="utf-8")
        return r


# ---------------------------------------------------------------- registro de modelos
def _modelo_del_repo():
    if not REPO.exists():
        return None
    m = MODELO_REPO
    base = re.sub(r"-R\d+$", "", m)                       # REP0-MOD2-R02 -> modelo REP0-MOD2, versión R02
    return Modelo(base, m[len(base) + 1:] or "R00", {
        "instantanea": REPO / "5_Documentacion" / "Compartir" / "NEXO_OBRA_solo_lectura.html",
        "cronograma": REPO / "1_Panel" / "datos" / "nexo_no_datos.json",
        "metrados": REPO / "3_Modelo_y_parametros" / f"metrados_{m}.json",
        "auditoria": REPO / "3_Modelo_y_parametros" / f"auditoria_{m}.json",
        "parametros": REPO / "3_Modelo_y_parametros" / f"parametros_revit_{m}.json",
        "presupuesto": REPO / "5_Documentacion" / f"Presupuesto_Estructuras_{m}_v4.xlsx",
        "registros_iniciales": REPO / "3_Modelo_y_parametros" / f"registros_{m}.json",
    }, nombre=f"{base} (repo del equipo)", origen=f"repo {REPO.name}")


def _modelo_de_carpeta(d: Path):
    man = json.loads((d / "modelo.json").read_text(encoding="utf-8"))
    arch = {k: (d / v).resolve() for k, v in man["archivos"].items()}
    for k, p in arch.items():                             # el manifiesto no puede apuntar fuera de su carpeta
        if d.resolve() not in p.parents:
            raise ValueError(f"{d}/modelo.json: '{k}' apunta fuera de la carpeta")
    return Modelo(man["id"], man["version"], arch, nombre=man.get("nombre"), publicado=man.get("publicado"),
                  origen=f"publicado por {man.get('autor', '?')}" + (f": {man['comentario']}" if man.get("comentario") else ""))


_reg = {"firma": None, "modelos": {}}
_reg_lock = threading.Lock()


def _firma():
    fs = sorted(f"{p}{p.stat().st_mtime_ns}" for p in MODELOS.glob("*/*/modelo.json")) if MODELOS.exists() else []
    return hashlib.sha1(("|".join(fs) + str(REPO)).encode()).hexdigest()


def registro():
    """{id_modelo: {version: Modelo}}. Se relee solo si se publicó algo nuevo."""
    f = _firma()
    with _reg_lock:
        if _reg["firma"] == f:
            return _reg["modelos"]
        viejos = {(m.id, m.version): m for vs in _reg["modelos"].values() for m in vs.values()}
        nuevos = {}
        cands = [_modelo_del_repo()]
        for man in (sorted(MODELOS.glob("*/*/modelo.json")) if MODELOS.exists() else []):
            try:
                cands.append(_modelo_de_carpeta(man.parent))
            except Exception as ex:  # noqa: BLE001
                print(f"[modelos] se ignora {man}: {ex}")
        for m in cands:
            if m is None or m.faltantes():
                continue
            m = viejos.get((m.id, m.version), m)           # conserva lo ya cargado en memoria
            nuevos.setdefault(m.id, {})[m.version] = m
        _reg.update(firma=f, modelos=nuevos)
        return nuevos


def clave_version(v):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", v)]


def listar():
    out = []
    for mid, vs in sorted(registro().items()):
        orden = sorted(vs, key=clave_version)
        out.append({"id": mid, "nombre": vs[orden[-1]].nombre, "vigente": orden[-1],
                    "versiones": [vs[v].resumen() for v in reversed(orden)]})
    return out


def obtener(mid=None, version=None) -> Modelo:
    reg = registro()
    if not reg:
        raise LookupError("No hay modelos: define NEXO_REPO=/ruta/a/BIM-IA o publica uno en NEXO_MODELOS.")
    if mid not in reg:                                     # sin elección: el definido por el equipo, si no el del repo
        repo = re.sub(r"-R\d+$", "", MODELO_REPO)
        mid = next(x for x in (os.environ.get("NEXO_MODELO_DEFECTO"), repo, sorted(reg)[0]) if x in reg)
    vs = reg[mid]
    if version not in vs:
        version = sorted(vs, key=clave_version)[-1]       # por defecto, la versión vigente (la última)
    return vs[version]


# ---------------------------------------------------------------- modelo activo de la petición
_actual = contextvars.ContextVar("modelo_nexo", default=None)


def usar(mid=None, version=None) -> Modelo:
    m = obtener(mid, version)
    _actual.set(m)
    return m


def actual() -> Modelo:
    return _actual.get() or usar()


# API de módulo (la usan auditor, ml, narrador, parte_diario): siempre sobre el modelo activo
def huellas():                    return actual().huellas               # noqa: E704
def estado() -> Path:             return actual().estado                # noqa: E704
def datos_base():                 return actual().instantanea["datos"]  # noqa: E704
def geometria_bytes():            return actual().geometria_bytes       # noqa: E704
def cronograma():                 return actual().cronograma            # noqa: E704
def metrados_modelo():            return actual().metrados_modelo       # noqa: E704
def auditoria_modelo():           return actual().auditoria_modelo      # noqa: E704
def actividades_por_elemento():   return actual().actividades_por_elemento  # noqa: E704
def apu():                        return actual().apu                   # noqa: E704
def partidas():                   return actual().partidas              # noqa: E704
def elementos():                  return actual().elementos             # noqa: E704
def ruta_registros() -> Path:     return actual().ruta_registros()      # noqa: E704


def leer_registros() -> dict:
    o = json.loads(ruta_registros().read_text(encoding="utf-8"))
    o.setdefault("elementos", {})
    o.setdefault("global", "")
    return o


def parsear(reg: str):
    """'aaaa-mm-dd|item|cantidad;...' -> lista de (fecha, item, cantidad)."""
    out = []
    for x in (reg or "").split(";"):
        p = x.split("|")
        if len(p) == 3:
            try:
                out.append((p[0], p[1], float(p[2])))
            except ValueError:
                pass
    return out


def ejecutado_por_elemento() -> dict:
    out = {}
    for k, n in leer_registros()["elementos"].items():
        acc = {}
        for _, it, q in parsear(n.get("registro", "")):
            acc[it] = acc.get(it, 0.0) + q
        out[int(k)] = acc
    return out
