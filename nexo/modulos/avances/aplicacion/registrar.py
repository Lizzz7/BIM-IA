"""Caso de uso transaccional local. Reintentos y registros se guardan juntos en JSON."""
import hashlib
import json
from nexo.modulos.avances.dominio.reglas import aplicar
from .puertos import RepositorioRegistros


def ejecutar(repo: RepositorioRegistros, pedido, partidas, elementos, version, simular=False):
    actuales = repo.leer()
    request_id = pedido.get("request_id")
    if request_id is not None and (not isinstance(request_id, str) or not 1 <= len(request_id) <= 120):
        raise ValueError("Identificador de solicitud no válido.")
    huella = hashlib.sha256(json.dumps(
        {"fecha": pedido.get("fecha"), "registros": pedido.get("registros"), "version": version},
        sort_keys=True, allow_nan=False).encode()).hexdigest()
    solicitudes = actuales.get("_solicitudes", {})
    if request_id and not simular and request_id in solicitudes:
        previo = solicitudes[request_id]
        if previo["huella"] != huella:
            raise ValueError("La solicitud ya fue registrada con otro contenido o versión.")
        respuesta = dict(previo["respuesta"])
        ids = previo.get("elementos", [])
        respuesta["elementos"] = [{"id": i, **actuales["elementos"][str(i)]}
                                 for i in ids if str(i) in actuales["elementos"]]
        respuesta["registroGlobal"] = actuales.get("global", "")
        return {**respuesta, "reintento": True}
    nuevos, r = aplicar(actuales, pedido, partidas, elementos)
    # El lote confirmado es atómico: nada se guarda si una fila es inválida.
    abortado = bool(r["rechazados"]) and not simular
    aplicados = [] if abortado else r["aplicados"]
    if abortado:
        nuevos = actuales
    resultado = {"ok": True, "simulado": simular, "guardado": not simular and bool(aplicados),
                 "aplicados": aplicados, "rechazados": r["rechazados"], "alertas": r["alertas"],
                 "notas": ["Lote cancelado: corrige los registros rechazados y reenvía."] if abortado else [],
                 "monto_cd": 0 if abortado else r["monto_cd"],
                 "elementos": [] if simular or abortado else [
                     {"id": i, **nuevos["elementos"][str(i)]} for i in sorted(r["tocados"])],
                 "registroGlobal": nuevos.get("global", ""), "reintento": False}
    if resultado["guardado"]:
        if request_id:
            # No duplicar cadenas completas de historial en cada recibo.
            resumen = {k: v for k, v in resultado.items() if k not in ("elementos", "registroGlobal")}
            solicitudes[request_id] = {"huella": huella, "respuesta": resumen,
                                       "elementos": sorted(r["tocados"])}
            nuevos["_solicitudes"] = solicitudes
        repo.guardar(nuevos)
    return resultado
