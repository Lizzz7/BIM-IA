import sys
from nexo.modulos.auditoria.aplicacion import analizar as implementacion
sys.modules[__name__] = implementacion
