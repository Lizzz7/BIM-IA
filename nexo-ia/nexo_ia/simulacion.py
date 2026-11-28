import sys
from nexo.modulos.evidencia_bim.aplicacion import simulacion as implementacion
sys.modules[__name__] = implementacion
