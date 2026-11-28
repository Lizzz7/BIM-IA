"""Monolito modular NEXO. Puente temporal para los adaptadores históricos."""
from pathlib import Path
import sys

LEGADO = Path(__file__).resolve().parent.parent / "nexo-ia"
if str(LEGADO) not in sys.path:
    sys.path.insert(0, str(LEGADO))
