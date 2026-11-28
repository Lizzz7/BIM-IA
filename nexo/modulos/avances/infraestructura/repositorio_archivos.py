from pathlib import Path
import json
from nexo.plataforma.persistencia.archivos import escribir_json


class RegistrosJSON:
    def __init__(self, ruta):
        self.ruta = Path(ruta)

    def leer(self):
        return json.loads(self.ruta.read_text(encoding="utf-8"))

    def guardar(self, registros):
        escribir_json(self.ruta, registros)
