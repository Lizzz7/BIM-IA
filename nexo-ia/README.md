# NEXO OBRA · capa de IA (Reto 3 · Hackathon BIM + IA UNSA 2026)

IA integrada **dentro** del panel de valorizaciones NEXO OBRA, sin Revit y sin tocar el repo `BIM-IA`.
Soporta **varias obras y versiones de modelo**, y se puede publicar como link (PC y celular).

## Arrancar (Mac / Linux / Windows)

```bash
# carpetas lado a lado:  ./BIM-IA  (repo del equipo)   ./nexo-ia  (esta carpeta)
cd nexo-ia
pip3 install -r requirements.txt
python3 servidor.py                      # → http://127.0.0.1:8770
python3 pruebas/test_ia.py               # 10 pruebas (usa carpetas temporales)
python3 pruebas/evaluar_parte_diario.py  # precisión del parte diario asistido
```
Si el repo está en otra ruta: `NEXO_REPO=/ruta/a/BIM-IA python3 servidor.py`. Para reiniciar la demo: borrar `estado/`.

## Dónde vive cada cosa

| Qué | Dónde | Quién escribe |
|---|---|---|
| Código del panel y scripts | repo `BIM-IA` (git) | programadores |
| **Versiones publicadas del modelo** (inmutables) | `modelos/<obra>/<version>/` + `modelo.json` | modelador, con «Publicar» |
| **Estado de obra**: registros de metrado, decisiones, bitácora IA, caché | `estado/<obra>/` | el panel (residentes, costos) |
| El modelo `.rvt` | PC del modelador | Revit |

El repo se lee en solo lectura y además se registra como una obra más (`REP0-MOD2`, versión `R02`).

## Publicar una versión nueva del modelo (sin cambiar el complemento)

1. El modelador exporta desde Revit como hoy (NexoMetrados + instantánea).
2. Empaqueta: `python3 empaquetar_version.py --repo ../BIM-IA --rvt REP0-MOD2-R03 --id REP0-MOD2 --version R03 --autor "Ana" --comentario "placas eje 3"`
3. Publica:  `curl -X POST --data-binary @REP0-MOD2_R03.zip -H "X-Nexo-Admin: $NEXO_TOKEN_ADMIN" https://<servidor>/api/admin/publicar`
   (o copiar la carpeta descomprimida a `modelos/REP0-MOD2/R03/`).

La versión aparece en el selector **Modelo / Versión** de la cabecera. La más reciente es la vigente.
Una versión no se puede sobrescribir (→ 409): un cambio en Revit = una versión nueva.
El ML y la auditoría de la versión nueva se calculan en segundo plano al publicar.

## Ir y volver de Revit

- **Revit → panel**: publicar versión (arriba).
- **Panel → Revit**: el avance **no se escribe dentro del .rvt**. Igual que en el complemento original
  (`Escritura.cs`: «nunca en el modelo de Revit»). `GET /api/registros.json` (o Configuración → Trazabilidad →
  «descargar registros») entrega el archivo en el **mismo formato** que `registros_<modelo>.json` del complemento:
  se copia junto a los datos y el complemento NexoObraNO lo lee tal cual.

## Seguridad para el link

| Variable | Efecto |
|---|---|
| `NEXO_TOKEN=…` | Cualquiera con el link **ve**; para registrar o decidir hay que entrar una vez con `/entrar?token=…` (cookie 30 días) |
| `NEXO_TOKEN_ADMIN=…` | Necesario para publicar versiones |
| `NEXO_SOLO_LECTURA=1` | Vitrina: nadie escribe |
| `NEXO_LLM_POR_MINUTO=30` | Límite de llamadas a la IA por IP |
| `NEXO_MODELO_DEFECTO=…` | Obra que ve quien entra sin haber elegido |
Sin `NEXO_TOKEN` (modo local) se puede escribir libremente.

## Deployment (link público)

```bash
docker build -t nexo-ia .
docker run -p 8770:8770 -v nexo-data:/data -e NEXO_TOKEN=… -e NEXO_TOKEN_ADMIN=… nexo-ia
```
`/data` **tiene que ser un volumen persistente** (versiones publicadas + registros). Proveedores con volumen: Render
(Disk), Fly.io (volumes), Railway (volumes), IBM Code Engine o Cloud Run con almacenamiento montado.
Una instancia atiende bien a 100 usuarios simultáneos (medido: p95 ≈ 1 s en datos y 3D, ≈ 4 s en la auditoría).
Para varias instancias, el estado de obra debe pasar a Postgres/Supabase (`4_Python/supabase_esquema.sql`).

### Activar un LLM (opcional; sin él todo funciona con plantillas verificadas)
```bash
NEXO_LLM=ollama   NEXO_LLM_MODELO=granite3.3:8b python3 servidor.py        # local, sin internet (ollama pull granite3.3:8b)
NEXO_LLM=watsonx  WATSONX_APIKEY=… WATSONX_PROJECT_ID=… python3 servidor.py # IBM Granite en watsonx.ai
NEXO_LLM=openai   OPENAI_API_KEY=… NEXO_LLM_MODELO=gpt-4o-mini python3 servidor.py
NEXO_LLM=anthropic ANTHROPIC_API_KEY=… python3 servidor.py
```

## Las tres capas de IA (la IA nunca produce el número final)

1. **Reglas** (`nexo_ia/auditor.py`), cada hallazgo con fuente, fórmula y valores:
   - R01 solapes de concreto sin unir (97 · S/ 1,232.57)
   - R02 f'c del tipo ≠ material
   - R03 elemento sin material
   - R04 mayor metrado real
   - R04b falsas alarmas por coma flotante del complemento
   - R05 secuencia constructiva
   - R06 P.U. incoherente con el f'c
2. **ML** (`nexo_ia/ml.py`): RandomForest que aprende la geometría de cada grupo sin leer el nombre del tipo.
   Validación cruzada, exactitud 97 %. Se entrena una vez por versión publicada y queda en caché.
3. **LLM** (`narrador.py`, `parte_diario.py`):
   - Solo redacta o interpreta. Salida JSON validada con valores de una lista cerrada.
   - `verificador.py` rechaza números que no estén en la evidencia.
   - Una sola llamada aunque 20 usuarios pidan lo mismo. Caché por obra y versión.
   - Todo queda en `estado/<obra>/bitacora_ia.jsonl`.

## Límites (decirlos en la presentación)
- Herramienta académica: los hallazgos son para revisión de un ingeniero; ninguno se aplica solo.
- Los registros de avance del repo son **datos de prueba**. Los 12 casos del parte diario los escribió el equipo de desarrollo.
- Los registros usan el `ElementId` de Revit, como el complemento. En producción conviene el `UniqueId`, que es estable.
- El clasificador aprende de las etiquetas de `metrados.py`: detecta casos raros respecto del resto del modelo, no errores absolutos.
