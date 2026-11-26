# NEXO OBRA · BIM + revisión de costos

Prototipo académico para el reto 3 de la Hackathon BIM + IA. Usa las exportaciones
existentes para revisar presupuestos y valorizaciones **sin tener Revit abierto**.
No modifica los modelos, presupuestos Excel ni JSON originales.

## Ejecutar en Windows

Desde PowerShell, en la carpeta del repositorio (Python 3.10 o superior):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe nexo-ia\servidor.py
```

Abre **http://127.0.0.1:8771/**. Para detener: `Ctrl+C`.
Si ya creaste el entorno, solo necesitas el último comando.
No reutilices los entornos antiguos dentro de `nexo-ia/`.

En Linux/WSL:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python nexo-ia/servidor.py
```

El puerto 8771 no interfiere con el complemento de Revit (8770).
También admite `--puerto 8780` y `--estado ruta/a/otra/carpeta`.

## Recorrido de demostración

1. **Inicio / Visor 3D:** datos y geometría exportados, sin conexión a Revit.
2. **Revisión IA → Auditoría → Analizar presupuesto:** evidencia, cobertura,
   diferencias y advertencias sobre los datos existentes.
3. Selecciona **Caso controlado SIMULADO** y analiza: seis hallazgos esperados,
   dos registros válidos de control y S/ 600 de exceso por revisar. No es ahorro
   real ni una medición de precisión generalizable. No altera avances.
4. Abre un hallazgo, consulta su evidencia y los elementos en 3D. Confirma o
   descarta con motivo. Las decisiones quedan en SQLite, no corrigen cantidades.
5. **Revisar asignaciones:** elige elemento y clase; consulta candidatas
   compatibles con unidad y resistencia explícita, cuando está disponible.
6. **Comparar versiones:** contrasta v3 y v4. En los archivos actuales la
   diferencia de costo directo es S/ 34 390,75. Se descompone en cantidad, precio,
   altas, bajas, cambios de unidad y redondeo; se conservan referencias y hashes.
7. **Escenarios APU:** escribe “El precio del acero sube 5 %”, prepara la propuesta
   y confirma el supuesto. El motor recalcula solo las partidas afectadas.
   Es simulación de costo directo, no predicción ni actualización contractual.
8. Descarga los informes JSON para inspeccionar o contrastar los resultados.

## Qué es IA y qué no

El motor de reglas, la comparación y los cálculos funcionan **sin proveedor**.
La búsqueda local TF-IDF y la interpretación local por patrones están etiquetadas
como **sin IA**. No hay modelos entrenados con los avances simulados.

La integración opcional utiliza una API **OpenAI-compatible**:

- Embeddings y similitud coseno para ordenar partidas candidatas.
- Un modelo de lenguaje para preparar explicaciones cualitativas con citas al
  hallazgo, o interpretar solicitudes de escenarios.
- Se validan formatos, catálogo, citas y límites antes de utilizar las propuestas.
- El modelo no calcula importes, no aprueba pagos y no modifica datos automáticamente.

Configura las variables en la misma terminal **antes de iniciar el servidor**:

```powershell
$env:NEXO_IA_BASE_URL = "https://TU-PROVEEDOR/v1"
$env:NEXO_IA_MODEL = "MODELO-DE-CHAT-DISPONIBLE"
$env:NEXO_IA_EMBED_MODEL = "MODELO-DE-EMBEDDINGS-DISPONIBLE"
$env:NEXO_IA_API_KEY = "TU-CLAVE"
.\.venv\Scripts\python.exe nexo-ia\servidor.py
```

Usa nombres de modelos que realmente ofrezca tu proveedor. También admite una
API local compatible mediante HTTP en localhost. Chat y embeddings pueden
configurarse por separado, pero comparten URL y clave. No se lee `.env`
automáticamente. Las claves nunca se entregan al navegador.

La interfaz pide confirmación antes de enviar al proveedor el hallazgo o las
descripciones necesarias. No envía geometría ni archivos completos. Revisa
autorizaciones, privacidad y posibles costos del proveedor.
Las pruebas del proveedor usan respuestas simuladas: **no acreditan una
conexión real ni calidad de un modelo externo**.

## Persistencia y fuentes

- `nexo-ia/servidor.py`: servidor HTTP local.
- `nexo-ia/nexo_ia/`: adaptador, SQLite, auditoría, comparación, APU e IA opcional.
- `1_Panel/panel_fuente.html`: panel fuente.
- `1_Panel/revision_ia.js` y `.css`: interfaz del nuevo módulo.
- `3_Modelo_y_parametros/`: exportaciones existentes de referencia.
- `5_Documentacion/`: presupuestos y geometría de la instantánea.
- `.nexo-local/`: registros y decisiones locales; excluido de Git.

La primera ejecución copia los registros de referencia a SQLite. Las siguientes
usan esa copia; no vuelven a importar los JSON. Haz respaldo de `.nexo-local/`
para conservar avances y revisiones. Los documentos de valorización siguen
guardados en el navegador, separados por proyecto; no son persistencia compartida.
Las nuevas valorizaciones conservan también partidas, PU e indirectos del presupuesto.
Los documentos antiguos no adquieren retroactivamente esa garantía.
Las claves antiguas del navegador no se borran ni se migran automáticamente.

El servidor ensambla el panel fuente al abrirlo. Para regenerar el `index.html`
utilizado por el complemento existente:

```powershell
.\.venv\Scripts\python.exe 1_Panel\armar_panel.py
```

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Incluyen auditoría con controles negativos, corte temporal, ausencia de datos,
reconciliación monetaria, idempotencia, transacciones, persistencia, validación
de respuestas de IA simuladas y controles HTTP de origen y host.

Prueba de navegador opcional (dependencias solo de desarrollo):

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe tests\navegador_nexo.py
```

## Límites de esta entrega

- No incluye importador genérico, segunda obra, lector IFC ni autenticación multiusuario.
- El caso contiene avances de prueba y precios/criterios con supuestos.
- Una coincidencia de registros o una diferencia modelo/presupuesto es una
  advertencia, no prueba de duplicidad, omisión, pérdida o fraude.
- El total monetario de auditoría suma solo excesos por partida, sin duplicar
  sus detalles por elemento. No hay costo real para calcular sobrecostos reales.
- Las versiones se corresponden por código de partida; un cambio de código
  aparece como alta/baja. No se infieren causas documentales o geométricas.
- El escenario mantiene rendimientos, cantidades, otros recursos e indirectos;
  sustituye los parciales del material seleccionado con redondeo explícito.
- La geometría procede de la instantánea existente, no de una sincronización viva.
- Es un servidor para uso local experimental, no para exponer a Internet.
  El modo de lectura del panel no sustituye permisos de servidor.
- Ningún resultado sustituye la revisión y aprobación del profesional responsable.
