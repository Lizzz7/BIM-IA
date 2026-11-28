import sys
from nexo.modulos.avances.aplicacion import parte_diario as implementacion
sys.modules[__name__] = implementacion
