"""Reemplazo atómico en el mismo directorio, sin base de datos nueva."""
import json
import os
from pathlib import Path
import tempfile


def escribir_json(ruta, valor):
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=ruta.parent,
                                         prefix="." + ruta.name, suffix=".tmp", delete=False) as f:
            tmp = Path(f.name)
            json.dump(valor, f, ensure_ascii=False, allow_nan=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, ruta)
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()
