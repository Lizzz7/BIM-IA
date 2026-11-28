"""Adaptador compatible del caso de uso de avances. Conserva aplicar() para simulaciones."""
from nexo.modulos.avances.dominio.reglas import aplicar as aplicar_reglas, sumas
from nexo.modulos.avances.aplicacion.registrar import ejecutar
from nexo.modulos.avances.infraestructura.repositorio_archivos import RegistrosJSON
from . import bitacora, datos as D


def aplicar(reg, ped):
    return aplicar_reglas(reg, ped, D.partidas(), D.elementos())


def guardar_registros(reg):
    RegistrosJSON(D.ruta_registros()).guardar(reg)


def registrar(ped):
    if not isinstance(ped, dict) or not isinstance(ped.get("registros"), list):
        raise ValueError("Se esperaba un lote de registros.")
    if len(ped["registros"]) > 10000:
        raise ValueError("Lote demasiado grande.")
    if "simular" in ped and not isinstance(ped["simular"], bool):
        raise ValueError("simular debe ser booleano.")
    simular = ped.get("simular", False) or D.en_simulacion()
    with D.candado("registros"):
        if simular:
            reg, r = aplicar(D.leer_registros(), ped)
            return {"ok": True, "simulado": True, "guardado": False, **{
                k: r[k] for k in ("aplicados", "rechazados", "alertas", "monto_cd")},
                "elementos": [], "registroGlobal": reg.get("global", ""), "notas": []}
        r = ejecutar(RegistrosJSON(D.ruta_registros()), ped, D.partidas(), D.elementos(),
                     D.huellas()["version_datos"])
        if r["guardado"] and not r["reintento"]:
            bitacora.anotar("metrado", fecha=ped.get("fecha"), n=len(r["aplicados"]), monto_cd=r["monto_cd"],
                           origen=ped.get("origen", "panel"), usuario=ped.get("_usuario"))
        return r
