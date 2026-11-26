"""Estado separado de los archivos originales; transacciones e idempotencia."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import uuid


class Almacen:
    def __init__(self, ruta, registros):
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self.conexion() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS registros (
                    id TEXT PRIMARY KEY, element_id INTEGER NOT NULL, item TEXT NOT NULL,
                    fecha TEXT NOT NULL, cantidad TEXT NOT NULL, fuente TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS solicitudes (
                    id TEXT PRIMARY KEY, huella TEXT NOT NULL, respuesta TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisiones (
                    hallazgo TEXT PRIMARY KEY, estado TEXT NOT NULL, motivo TEXT NOT NULL, fecha TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS eventos (
                    id INTEGER PRIMARY KEY, hallazgo TEXT NOT NULL, estado TEXT NOT NULL,
                    motivo TEXT NOT NULL, fecha TEXT NOT NULL);
            """)
            if not db.execute("SELECT 1 FROM meta WHERE clave='inicializado'").fetchone():
                db.executemany("INSERT INTO registros VALUES (:id,:element_id,:item,:fecha,:cantidad,:fuente)", registros)
                db.execute("INSERT INTO meta VALUES ('inicializado','1')")

    @contextmanager
    def conexion(self):
        db = sqlite3.connect(self.ruta, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def registros(self):
        with self.conexion() as db:
            return [dict(r) for r in db.execute("SELECT * FROM registros ORDER BY rowid")]

    def registrar(self, request_id, huella, preparar, simular=False):
        # El callback valida TODO el lote antes de insertar. Un reintento no duplica cantidades.
        with self.conexion() as db:
            db.execute("BEGIN IMMEDIATE")
            anterior = db.execute("SELECT * FROM solicitudes WHERE id=?", (request_id,)).fetchone()
            if anterior and not simular:
                if anterior["huella"] != huella:
                    raise ValueError("La solicitud ya existe con otro contenido.")
                return json.loads(anterior["respuesta"])
            actuales = [dict(r) for r in db.execute("SELECT * FROM registros ORDER BY rowid")]
            nuevos, respuesta = preparar(actuales)
            if not simular:
                for r in nuevos:
                    db.execute("INSERT INTO registros VALUES (?,?,?,?,?,?)",
                               (uuid.uuid4().hex, r["element_id"], r["item"], r["fecha"],
                                r["cantidad"], "Registro local confirmado"))
                db.execute("INSERT INTO solicitudes VALUES (?,?,?)",
                           (request_id, huella, json.dumps(respuesta, ensure_ascii=False)))
            return respuesta

    def revisiones(self):
        with self.conexion() as db:
            return {r["hallazgo"]: dict(r) for r in db.execute("SELECT * FROM revisiones")}

    def revisar(self, hallazgo, estado, motivo):
        if estado not in ("Pendiente", "Confirmado", "Descartado"):
            raise ValueError("Estado de revisión no válido.")
        if not isinstance(motivo, str) or not motivo.strip() or len(motivo) > 2000:
            raise ValueError("Escribe el motivo de la revisión (máximo 2000 caracteres).")
        f = datetime.now(timezone.utc).isoformat()
        with self.conexion() as db:
            db.execute("INSERT OR REPLACE INTO revisiones VALUES (?,?,?,?)", (hallazgo, estado, motivo.strip(), f))
            db.execute("INSERT INTO eventos(hallazgo,estado,motivo,fecha) VALUES (?,?,?,?)",
                       (hallazgo, estado, motivo.strip(), f))
        return {"ok": True, "estado": estado, "motivo": motivo.strip(), "fecha": f}
