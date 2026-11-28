import sys
from nexo.modulos.evidencia_bim.aplicacion import sintetico as implementacion
sys.modules[__name__] = implementacion
