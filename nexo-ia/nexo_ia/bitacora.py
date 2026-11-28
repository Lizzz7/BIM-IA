import sys
from nexo.plataforma.observabilidad import bitacora as implementacion
sys.modules[__name__] = implementacion
