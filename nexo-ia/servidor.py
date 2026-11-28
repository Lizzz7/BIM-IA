"""Arranque compatible: python nexo-ia/servidor.py. Preferido: python -m nexo.bootstrap."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nexo.api import http as implementacion

if __name__ == "__main__":
    implementacion.main()
else:
    sys.modules[__name__] = implementacion
