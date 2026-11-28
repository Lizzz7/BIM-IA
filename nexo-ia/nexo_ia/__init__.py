"""Fachadas de compatibilidad; las implementaciones viven en el paquete nexo."""
from pathlib import Path
import sys

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))
