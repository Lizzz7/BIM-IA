import sys
from nexo.integraciones.ia import clasificador as implementacion
sys.modules[__name__] = implementacion
