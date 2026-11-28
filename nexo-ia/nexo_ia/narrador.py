import sys
from nexo.modulos.auditoria.aplicacion import narrar as implementacion
sys.modules[__name__] = implementacion
