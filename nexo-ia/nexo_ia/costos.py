import sys
from nexo.modulos.valorizaciones.aplicacion import consultas as implementacion
sys.modules[__name__] = implementacion
