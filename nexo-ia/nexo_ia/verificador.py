import sys
from nexo.modulos.auditoria.dominio import verificador as implementacion
sys.modules[__name__] = implementacion
