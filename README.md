# NEXO OBRA · BIM + IA para revisión de costos

Integración progresiva de `claude/modular` y BIM2, con aportes seleccionados de
`features/liz`. Monolito modular DDD; **sin migraciones de base de datos**.
Se mantienen los archivos JSON/JSONL y las exportaciones existentes.

## Abrir el proyecto

Desde la raíz, Python 3.10 o superior:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r nexo-ia\requirements.txt
.\.venv\Scripts\python.exe -m nexo.bootstrap
```

En Linux/macOS: `python3 -m venv .venv`, instalar con
`.venv/bin/python -m pip install -r nexo-ia/requirements.txt` y ejecutar
`.venv/bin/python -m nexo.bootstrap`.

Abre **http://127.0.0.1:8770/**. Si el complemento de Revit ocupa ese puerto,
define `NEXO_PUERTO=8771` antes de arrancar (`$env:NEXO_PUERTO="8771"` en PowerShell).
El comando anterior `python nexo-ia/servidor.py` sigue siendo compatible.

## Recorrido

1. **Inicio / Visor:** datos BIM exportados, sin Revit abierto.
2. **Parte diario:** texto asistido, consulta de costos y propuesta validable.
3. **Avance por dron:** cargar nube o generar caso **sintético**. IFC opcional para
   correspondencias y transformación de coordenadas. Historial y visor conservados.
4. **Control:** auditoría con evidencia, ML de clasificación y narración opcional.
5. **Valorizaciones:** costos y presupuesto, más **Cotizaciones y variaciones**:
   - Ingresar precio, unidad, fuente, fecha, IGV y alcance comparable.
   - Revisar qué recursos/APU y partidas cambian.
   - Guardar una revisión **propuesta**, sin activar un presupuesto ni aprobar pagos.
   - Comparar versiones por cantidades, precios, altas, bajas y redondeos.
6. **Configuración:** trazabilidad y exportación Power BI.

No hay una pantalla protagonista de porcentajes arbitrarios. El APU se usa para
cotizaciones documentadas y explicación de variaciones.

## Arquitectura y compatibilidad

Ver [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md). El código canónico vive en
`nexo/`; las fachadas de `nexo-ia/nexo_ia/` conservan los imports históricos.
`nexo-ia/nexo_ia/ifc_modelo.py` y `7_Dron/nube_desde_ifc.py` siguen funcionando.

Los archivos originales de modelos y presupuestos se leen sin sobrescribirlos.
El estado sigue en `nexo-ia/estado/<obra>/` por defecto, configurable con
`NEXO_ESTADO`. Cotizaciones propuestas en `<estado>/<obra>/cotizaciones/`.
Los registros y recibos de idempotencia se guardan juntos mediante reemplazo
atómico de JSON. Los bloqueos son por proceso; múltiples escritores en procesos
distintos **no están soportados** por este almacenamiento.

Las valorizaciones siguen en el navegador, ahora con claves separadas por obra.
Los nuevos documentos conservan PU e indirectos. Las claves anteriores se
preservan, pero no se migran automáticamente; la compatibilidad no garantiza
congelación retroactiva de documentos antiguos. Los documentos y presupuestos
no tienen un flujo multiusuario de aprobación nuevo en esta entrega.

## Pruebas

Ejecutar cada script desde la raíz, con el Python del entorno:

```text
python -m unittest discover -s tests -v
python nexo-ia/pruebas/test_ia.py
python nexo-ia/pruebas/test_costos.py
python nexo-ia/pruebas/test_escaneo.py
python nexo-ia/pruebas/humo_demo.py --rapido
```

La prueba IFC real se omite explícitamente si no defines
`NEXO_IFC_PRUEBA=/ruta/a/proyecto.ifc`; no hay IFC de prueba versionado.

Navegador opcional:

```text
python -m pip install playwright
python -m playwright install chromium
python tests/navegador_integracion.py
```

Las pruebas usan estado temporal. No borrar el estado de una obra para probar.
La regeneración del panel para el complemento sigue siendo
`python 1_Panel/armar_panel.py`.

## Límites importantes

- Los registros existentes son de prueba. Las métricas del escaneo son sintéticas;
  no prueban exactitud en vuelos reales.
- La nube sustenta una propuesta de concreto con cantidades del BIM: no mide
  acero oculto ni aprueba pagos. Observado e inferido se muestran por separado.
- Mala alineación declarada bloquea propuestas económicas. Se conserva el visor.
- Las cotizaciones solo comparan PEN y unidades compatibles. El alcance, flete,
  especificación y entrega requieren contraste humano.
- La explicación APU usa diferencias documentadas y conserva componentes no
  explicados; si faltan APU comparables, no inventa el recurso causante.
- LLM opcional: sin proveedor se usan plantillas/reglas, no generación real.
  Configuración y límites del flujo heredado en `nexo-ia/README.md`.
- El servidor es experimental. Exponerlo a Internet requiere revisión de
  autenticación, permisos, HTTPS, almacenamiento y límites de recursos.

Docker, si se utiliza, se construye desde **la raíz**:
`docker build -f nexo-ia/Dockerfile -t nexo .`.
No se incorpora ningún servicio de base de datos.
