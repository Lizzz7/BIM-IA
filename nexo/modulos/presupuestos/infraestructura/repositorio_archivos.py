"""Revisiones propuestas inmutables. No se activa ni se sobrescribe el presupuesto."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


class RevisionesJSON:
    def __init__(self, carpeta):
        self.carpeta = Path(carpeta)

    def guardar(self, propuesta):
        contenido = json.dumps(propuesta, sort_keys=True, ensure_ascii=False, allow_nan=False)
        identidad = hashlib.sha256(contenido.encode()).hexdigest()[:24]
        self.carpeta.mkdir(parents=True, exist_ok=True)
        ruta = self.carpeta / (identidad + ".json")
        from nexo.plataforma.persistencia.archivos import escribir_json
        # El caso de uso se ejecuta bajo candado por obra; reintentar conserva la revisión.
        if not ruta.exists():
            escribir_json(ruta, {"id": identidad, "estado": "Propuesta, no aprobada",
                                "creada": datetime.now(timezone.utc).isoformat(), "propuesta": propuesta})
        return identidad
