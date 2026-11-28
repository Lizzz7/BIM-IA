import sys
from nexo.integraciones.nubes_puntos import archivos as implementacion
sys.modules[__name__] = implementacion
