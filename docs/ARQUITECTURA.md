# NEXO: integración DDD progresiva

Base: `claude/modular` (`7b466add`), que hereda Soph y BIM2. Las ramas del
primer dron y BIM2 contienen commits equivalentes con hashes diferentes: no se
fusionan dos veces. Las mejoras de Liz se portan selectivamente, sin su SQLite.

## Límites

- **Proyectos:** versiones publicadas, correspondencias y archivos de referencia.
- **Presupuestos:** APU, cotizaciones y revisiones comparables.
- **Avances:** validación y registro de cantidades, simulación e idempotencia.
- **Valorizaciones:** consultas económicas y documentos con referencia congelada.
- **Evidencia BIM:** escaneo, simulación, historial y propuestas observadas/inferidas.
- **Auditoría:** hallazgos, verificación y revisión humana.
- **Integraciones:** IFC/IfcOpenShell, nubes, Excel y proveedores IA.
- **Plataforma:** archivos, configuración y observabilidad.
- **API/web:** contrato HTTP e interfaz; composición en `nexo/bootstrap.py`.

La extracción es incremental: servicios heredados todavía usan las fachadas
`nexo_ia` y el contexto de obra. No se declara terminada una inversión de
dependencias global. Los nuevos casos de uso y reglas puras se construyen con
puertos explícitos; no se crean entidades o eventos vacíos para completar carpetas.

## Compatibilidad

`nexo-ia/nexo_ia/*.py` son alias al módulo canónico, no copias: comparten caché,
contexto, funciones y configuración. Se conservan imports históricos, pruebas,
`nexo-ia/nexo_ia/ifc_modelo.py` y `7_Dron/nube_desde_ifc.py`.
La implementación IFC está en `nexo/integraciones/ifc/modelo.py`.
El panel original no se reescribe: la API inyecta `nexo/web/nexo_ia.js`.

## Persistencia: ninguna migración

Se mantienen JSON/JSONL, modelos publicados y archivos de nube existentes.
No se añade SQLite, PostgreSQL, Supabase ni contenedores de base de datos.
Los bloqueos de archivo son locales al proceso; desplegar múltiples procesos
escritores requiere un mecanismo compartido antes de considerarse soportado.

## Arranque

Desde la raíz: `python -m pip install -r nexo-ia/requirements.txt`,
después `python -m nexo.bootstrap`. El arranque histórico
`python nexo-ia/servidor.py` también funciona.

Docker usa **la raíz del repositorio** como contexto:
`docker build -f nexo-ia/Dockerfile -t nexo .`

## Evidencia conservada

IFC–panel por Tag/ElementId, transformación y residuos; nubes simuladas y verdad
conocida; visor con entorno opcional, cámara centrada, transparencia y colores;
historial, simulación por etapas, chat y export Power BI.
Simulado no significa captura real; observado no significa aprobado para pago.
