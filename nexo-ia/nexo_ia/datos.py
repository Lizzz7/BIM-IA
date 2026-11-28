"""Compatibilidad con scripts existentes; sin duplicar estado ni cachés."""
import sys
from nexo.modulos.proyectos.infraestructura import repositorio_archivos as implementacion
sys.modules[__name__] = implementacion
