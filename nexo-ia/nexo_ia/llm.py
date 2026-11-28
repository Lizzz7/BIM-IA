import sys
from nexo.integraciones.ia import llm as implementacion
sys.modules[__name__] = implementacion
