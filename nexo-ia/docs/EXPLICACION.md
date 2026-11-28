# nexo-ia explicado para ingenieros de software

Este documento explica **qué hace la capa de IA, cómo está construida y cómo se despliega**, sin asumir conocimientos
de ingeniería civil. Cada término de obra se traduce a su equivalente en software.

---

## 0. El dominio en 2 minutos (glosario civil → software)

| Término de obra | Qué es, en términos de software |
|---|---|
| **Modelo BIM / Revit** | Una base de datos 3D del edificio: cada columna, viga o losa es un registro con geometría y propiedades. Revit es el editor (solo Windows). |
| **Elemento** | Una fila de esa base de datos (`id`, tipo, nivel, volumen, caja 3D…). El modelo de la demo tiene 1266. |
| **Partida** | Una línea del presupuesto: «concreto f'c=280 en columnas, S/ 610.63 por m³». Es el *catálogo de productos* con precio unitario (**P.U.**). |
| **Metrado** | La cantidad de una partida: «este elemento tiene 2.84 m³ de concreto». Cantidad × P.U. = costo. |
| **APU** (análisis de precio unitario) | La receta del P.U.: cuánto cemento, mano de obra y equipo lleva 1 m³. |
| **Valorización** | La factura mensual al cliente: lo construido ese mes (metrado ejecutado × P.U.). |
| **Parte diario** | El log diario del ingeniero de campo: «hoy se vaciaron columnas del piso 3». |
| **Registro de metrado** | Un evento `fecha|partida|cantidad` asociado a un elemento: *«el 10/06 se ejecutaron 2.84 m³ del elemento 394666»*. |
| **Paquete / sector** | Agrupaciones del cronograma: «Techo de Piso 3», «sector A». Equivalen a *epics* y *equipos*. |
| **f'c** | Resistencia del concreto (280, 350 kg/cm²). Más alto = más cemento = normalmente más caro. |
| **Solape** | Dos sólidos 3D que se intersectan sin estar «unidos» en Revit: el volumen común se cuenta dos veces → se cobra dos veces. |

**El problema de negocio (Reto 3):** la valorización mensual se arma a mano a partir del modelo, el presupuesto y los
partes diarios. Los errores (doble conteo, elemento mal clasificado, precio incoherente) cuestan dinero y se descubren tarde.
**La IA de este proyecto revisa esos datos antes de facturar y ayuda a registrar el avance.**

---

## 1. Arquitectura: qué es «el servidor» y por qué existe

### Antes (lo que construyó el equipo)

```
PC Windows
┌──────────────────────────────────────────────────────────────┐
│ Revit + complemento C# (NexoObraNO)                          │
│   └─ HttpListener en 127.0.0.1:8770  ← un servidor HTTP      │
│        GET  /api/datos       (lee el modelo en vivo)         │
│        GET  /api/geometria   (mallas 3D)                     │
│        POST /api/metrado     (guarda registros en un .json)  │
│                ▲                                             │
│ Navegador: 1_Panel/index.html (SPA en JS puro, WebGL propio) │
└──────────────────────────────────────────────────────────────┘
```
El panel es una **SPA** que solo sabe hacer `fetch("/api/...")`. No sabe que detrás está Revit.

### Ahora (nexo-ia)

```
Cualquier máquina (Mac, Linux, contenedor en la nube)
┌───────────────────────────────────────────────────────────────────────────┐
│ servidor.py  (Python stdlib: http.server.ThreadingHTTPServer)             │
│                                                                           │
│  ① Emulador del complemento: MISMAS rutas y MISMO contrato JSON           │
│     /api/datos /api/geometria /api/metrado  → el panel no nota diferencia │
│  ② Capa de IA:   /api/ia/auditoria  /narrar  /parte  /decision /bitacora  │
│  ③ Multi-obra:   /api/modelos  /api/admin/publicar  /api/registros.json   │
│  ④ Sirve index.html del repo e INYECTA <script src="/ia/nexo_ia.js">     │
│     (el archivo del repo no se modifica: se parchea la respuesta HTTP)    │
│                                                                           │
│  Lee (solo lectura):  repo BIM-IA + modelos/<obra>/<versión>/             │
│  Escribe:             estado/<obra>/  (registros, bitácora, caché)        │
└───────────────────────────────────────────────────────────────────────────┘
```
**Patrón:** *strangler / adapter*. Se reemplaza el backend (Revit) por otro que cumple el mismo contrato, y se extiende
la UI sin tocar su código: `nexo_ia.js` envuelve funciones globales del panel (`pControl`, `pParte`…) con un decorador
que llama a la original y luego dibuja la tarjeta de IA.

### ¿De dónde salen los datos si no hay Revit?
Revit ya exportó todo: la **instantánea** (`NEXO_OBRA_solo_lectura.html`) lleva incrustado
`window.NEXO_SNAPSHOT = {datos, geo}`, es decir, exactamente lo que devolverían `/api/datos` y `/api/geometria`.
`datos.py` lo extrae con una regex, una vez, y lo guarda en caché por hash.

---

## 2. Separación de datos (la decisión de diseño más importante)

| Tipo de dato | Ejemplo | Mutabilidad | Dónde vive |
|---|---|---|---|
| Código | panel, scripts | cambia con commits | git (repo BIM-IA) |
| **Artefacto** de una versión del modelo | metrados, geometría, presupuesto | **inmutable** | `modelos/<obra>/<versión>/` |
| **Estado** de la obra | registros diarios, decisiones, bitácora | append / mutable | `estado/<obra>/` |

- El repo es **solo lectura** para la app: git no es una base de datos (dos usuarios escribiendo = conflicto).
- Una versión publicada **nunca se sobrescribe** (409 si se intenta). Es como un *release tag*: así cada valorización
  puede decir con qué versión del modelo se calculó.
- El estado es **por obra** y **compartido entre versiones**: el avance pertenece al elemento, no a la versión.
- Hoy el estado es JSON en disco (sirve para 1 instancia). Escalar a N instancias = mover `estado/` a Postgres
  (el equipo ya tiene `4_Python/supabase_esquema.sql`).

**¿El avance vuelve a Revit?** No se escribe dentro del `.rvt` (tampoco en el diseño original: `Escritura.cs` lo dice).
El modelo es *diseño*; el avance es *operación*. `GET /api/registros.json` devuelve el archivo con el formato exacto que lee
el complemento, para sincronizarlo si se quiere ver en Revit.

---

## 3. Las tres capas de IA

```
                 ┌──────────────────────────────── evidencia (fuente, fórmula, valores) ─────────┐
datos del modelo ─► ① REGLAS (deterministas) ─┐                                                 │
                                              ├─► hallazgos ─► ③ LLM redacta ─► VERIFICADOR ─► UI
datos del modelo ─► ② ML (RandomForest) ──────┘                   (JSON schema)  (números ∈ evidencia)
```
**Principio: ningún número que ve el usuario lo inventa un modelo generativo.**
Las reglas y el ML calculan; el LLM solo redacta o interpreta, y su salida se valida.

### ① Reglas (`nexo_ia/auditor.py`)
Funciones puras `rXX() -> list[hallazgo]`. Cada hallazgo es un dict con: `id` (hash estable del contenido),
`regla`, `severidad`, `titulo`, `elementos` (IDs para resaltar en 3D), `partidas`, `impacto_soles`, y `evidencia`
`{fuente, formula, valores}`.

| Regla | Qué detecta (traducido) | Resultado en el modelo real |
|---|---|---|
| R01 | Intersecciones de sólidos no unidos → volumen cobrado 2 veces | 97 casos, S/ 1,232.57 |
| R02 | El nombre del tipo dice un f'c y el material otro (inconsistencia nombre vs. atributo) | 1 columna |
| R03 | Elemento presupuestado sin material asignado (campo obligatorio vacío) | 5 |
| R04 | Cantidad registrada > cantidad del contrato | 0 reales |
| R04b | **Bug del complemento**: compara floats sin tolerancia; sumar 2.839/7 siete veces da 2.8390000001 → falsa alarma | 2 |
| R05 | Se registró avance de una tarea antes que el de su predecesora (dependencias del cronograma) | 0 |
| R06 | Monotonía de precios: concreto más resistente más barato → APUs con métodos distintos | 3 pares |

### ② Machine learning (`nexo_ia/ml.py`)
- **Problema:** cada elemento tiene un *grupo* (columna, placa, viga…) asignado por reglas de texto sobre el nombre del
  tipo. Si el nombre está mal, el elemento cae en la partida equivocada (otro precio).
- **Modelo:** `RandomForestClassifier` (300 árboles, `class_weight="balanced"`) que predice el grupo **solo con
  geometría** (dimensiones de la caja, volumen, áreas de caras, compacidad, esbeltez) + categoría de Revit. *No ve el nombre.*
- **Evaluación honesta:** `cross_val_predict` con `StratifiedKFold(5)`: cada elemento lo predice un modelo que no lo
  vio al entrenar. Exactitud 97.2 %, F1 macro 0.936.
- **Uso:** cuando P(otro grupo) ≥ 0.85 y la etiqueta actual discrepa → hallazgo «ML1» con la probabilidad y el impacto
  en S/ de reclasificar. Caso real: columnas «C-2» de 0.25×1.30 m que geométricamente son *placas* (muros), con relación de lados 5.2.
- Pares indistinguibles por geometría (losa aligerada vs. maciza, mismo sólido) se excluyen a propósito.
- Se entrena **una vez por versión publicada** y se guarda en `estado/<obra>/cache/ml_<hash>.json`.

### ③ LLM (`llm.py`, `narrador.py`, `parte_diario.py`, `verificador.py`)
- **`llm.py`**: cliente HTTP sin dependencias para Ollama (local), watsonx (IBM Granite), APIs compatibles con OpenAI y
  Anthropic. Se elige con `NEXO_LLM`. Temperatura 0, salida JSON, validación con un mini JSON Schema y **1 reintento
  pasándole al modelo el error**. Sin LLM configurado → modo `plantilla` (la demo nunca depende de internet).
- **`narrador.py`**: hallazgo → `{observacion, accion, responsable, afecta_valorizacion}`.
  - El `responsable` es un `enum`, así que el modelo no puede inventar roles.
  - Caché por (obra, hallazgo, modelo).
  - **Single-flight**: un lock por clave, así que si 20 usuarios piden lo mismo a la vez, hay 1 llamada.
  - Si el proveedor falla por red, el respaldo no se cachea.
- **`verificador.py`** (anti-alucinación): extrae todos los números del texto generado (`1,232.57`, `86 %`, `0.634`),
  ignora códigos y fechas, y exige que cada uno exista en la evidencia (mismo redondeo, porcentaje o ±0.5 %). Si falla →
  reintento → plantilla. El resultado (✔ N números verificados) se muestra al usuario.
- **`parte_diario.py`**: texto libre → **intención** → resolución determinista.
  1. Intérprete (LLM o reglas regex): devuelve solo `{paquete, sector, grupos, clase, porcentaje}` con valores de una
     **lista cerrada** sacada del propio modelo (enum dinámico). Nunca devuelve IDs ni cantidades.
  2. Resolución determinista: filtra elementos y calcula cantidad = `min(total × %, lo que falta)`.
  3. La UI llama a `POST /api/metrado {simular:true}`: las validaciones del propio sistema se ejecutan sin guardar.
  4. El humano confirma.
  - Evaluación: `pruebas/evaluar_parte_diario.py` mide precisión/recall a nivel (elemento, partida) y error en S/.
    Con reglas: 11/12 casos.

### ④ Avance por dron (`escaneo.py`, `sintetico.py`, `nube_io.py`)
Es el equivalente a un *diff* entre el estado deseado (modelo) y el observado (nube de puntos del dron):
- **Entrada**: N puntos (x, y, z). **Referencia**: ~1 M puntos muestreados sobre los triángulos de cada elemento (la misma
  geometría que dibuja el visor 3D), en caché por versión de datos.
- **Alineación**: ICP rígido (Kabsch + KD-tree de scipy). Corrige el georreferenciado imperfecto (decenas de cm).
- **Cobertura**: fracción de puntos de referencia *propios* del elemento con un punto de la nube a < 10 cm.
- **Visibilidad**: z-buffer angular por cámara en numpy (sin GPU), usando la nube como obstáculo.
- **Reglas**: umbrales explícitos + propagación por soporte (grafo «A se apoya en B» calculado con cajas 3D).
- **Validación**: generador sintético con verdad conocida + `pruebas/evaluar_escaneo.py` (exactitud, precisión,
  exhaustividad, alertas detectadas, error de alineación). Pruebas automáticas en `pruebas/test_escaneo.py`.

### Trazabilidad (`bitacora.py`)
Log **append-only** en JSON Lines (`estado/<obra>/bitacora_ia.jsonl`). Cada evento guarda: timestamp, obra, versión,
**hash de los datos de entrada** (`version_datos` = sha256 de los archivos fuente), proveedor/modelo de IA, entrada, salida,
verificación, y las decisiones humanas (quién aceptó o descartó qué y por qué). Se descarga desde la UI.

---

## 4. Archivo por archivo

| Archivo | Responsabilidad | Detalles clave |
|---|---|---|
| `servidor.py` | Backend HTTP | `ThreadingHTTPServer` (un hilo por petición). Enrutamiento manual en `do_GET`/`do_POST`. Selección de obra por cookie/query (`D.usar()` en un `contextvar`). Cachés de respuestas serializadas+gzip por (obra, versión, clave). ETag en la geometría (304 si no cambió). Auth: cookie `nexo_token` (`/entrar?token=`), cabecera `X-Nexo-Admin` para publicar, `hmac.compare_digest`. Rate limit por IP (ventana de 60 s) para endpoints de LLM. Port de `Escritura.Registrar` (C#) con las mismas validaciones. Publicación de zip: valida rutas (`..`, absolutas), extrae a carpeta temporal y hace `rename` atómico. |
| `nexo_ia/datos.py` | Capa de acceso a datos | Clase `Modelo` = una versión publicada, con `cached_property` para cada archivo. Registro de obras/versiones (repo + carpeta `modelos/`), releído solo si cambia la firma de los manifiestos. Contextvar = «obra activa» de la petición (seguro entre hilos). |
| `nexo_ia/auditor.py` | Reglas deterministas | Ver §3①. `auditar()` combina reglas + ML, ordena por severidad e impacto. |
| `nexo_ia/ml.py` | Clasificador geométrico | Ver §3②. |
| `nexo_ia/llm.py` | Cliente LLM multi-proveedor | Ver §3③. |
| `nexo_ia/narrador.py` | Redacción de observaciones | Single-flight + caché + verificador + plantilla de respaldo. |
| `nexo_ia/verificador.py` | Anti-alucinación numérica | Regex + comparación tolerante. |
| `nexo_ia/parte_diario.py` | Texto → registros | Catálogo dinámico, intérprete LLM/reglas, resolución determinista. |
| `nexo_ia/bitacora.py` | Audit log | JSONL append-only, decisiones cacheadas por tamaño de archivo. |
| `web/nexo_ia.js` | UI inyectada | Decora funciones del panel; tarjetas en Control, Parte diario, Valorizaciones y Configuración; selector de obra/versión en la cabecera; oculta botones de escritura sin permiso. Usa `resaltar()` e `ir()` del panel para el 3D. |
| `empaquetar_version.py` | «Publicar versión» | Arma el zip `modelo.json` + archivos exportados por Revit. |
| `pruebas/test_ia.py` | 10 pruebas | Verificador, reglas con números reales, IDs únicos, LLM falso que alucina, single-flight con 20 hilos, % del parte diario, niveles, publicación inmutable y segura, aislamiento entre obras. |
| `pruebas/evaluar_parte_diario.py` + `casos_parte_diario.json` | Evaluación offline | Métricas del intérprete; compara reglas vs. LLM. |
| `Dockerfile` | Imagen para la nube | Clona el repo al construir, precalcula el ML, `/data` como volumen. |

---

## 5. Ejecutar: local vs. remoto

### Local
```bash
pip3 install -r requirements.txt
python3 servidor.py          # escucha en 127.0.0.1:8770 → solo tu máquina puede entrar
```
`127.0.0.1` (loopback) significa que **nadie más** puede conectarse, ni siquiera desde tu WiFi.

### Compartir YA desde tu Mac (túnel, 2 minutos, sin cuenta)
```bash
NEXO_TOKEN=<secreto> python3 servidor.py                # protege la escritura
brew install cloudflared && cloudflared tunnel --url http://localhost:8770
# imprime https://algo-aleatorio.trycloudflare.com  ← ese es el link (funciona en celulares)
# a tu equipo: https://…trycloudflare.com/entrar?token=<secreto>   (pueden registrar)
# al resto:    https://…trycloudflare.com                          (solo ven)
```
El túnel abre una conexión saliente desde tu Mac a Cloudflare, que publica una URL HTTPS. **Funciona solo mientras
tu Mac esté encendida y con el servidor corriendo**, y la URL cambia cada vez. Ideal para mostrar hoy.

### Remoto permanente (contenedor)
```bash
docker build -t nexo-ia . && docker run -p 8770:8770 -v nexo-data:/data -e NEXO_TOKEN=… -e NEXO_TOKEN_ADMIN=… nexo-ia
```
En un PaaS (Render, Fly.io, Railway…): conectar el repo, elegir «Docker», definir los secretos como variables de
entorno y montar un **disco persistente en `/data`**. Sin disco, cada reinicio borra registros y versiones publicadas
(aceptable solo para una demo en solo lectura). La URL es fija y no depende de tu Mac.

### Rendimiento medido (1 instancia, 100 usuarios simultáneos, 2 obras)
| Ruta | p95 |
|---|---|
| `/api/datos` | 1.45 s |
| `/api/geometria` (3.7 MB → 576 KB gzip) | 1.01 s |
| `/api/ia/auditoria` | 3.97 s |
Antes de cachear la serialización: p95 de 24.6 s en `/api/datos`.

---

## 6. Límites conocidos
- Estado en archivos → una sola instancia. Para escalar horizontalmente: Postgres.
- El LLM real no se probó en el entorno de desarrollo (sin clave): las pruebas usan un LLM falso; sin LLM todo funciona con plantillas verificadas.
- Los registros usan el `ElementId` de Revit, que puede cambiar entre versiones; en producción conviene el `UniqueId`, que es estable.
- Los datos de avance del repo son de prueba; los casos del parte diario los escribió el equipo de desarrollo.
- El `Dockerfile` no se construyó en el entorno de desarrollo (no había Docker).
