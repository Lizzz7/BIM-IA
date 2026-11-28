import sys
from nexo.integraciones.excel import exportar as implementacion
sys.modules[__name__] = implementacion
