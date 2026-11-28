"""Se conserva esta entrada pública para el flujo IFC y nube_desde_ifc.py."""
import sys
from nexo.integraciones.ifc import modelo as implementacion
sys.modules[__name__] = implementacion
