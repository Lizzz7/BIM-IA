# 7_Dron · captura con DJI Mini 5 Pro → nube de puntos → avance en NEXO OBRA

Flujo completo:

```
planificador_dron.py ──► Litchi Hub (web) ──► KMZ ──► DJI Fly (Waypoints) ──► vuelo
        ──► fotos ──► WebODM ──► nube .laz/.ply (+ .rcp en ReCap para Revit)
        ──► Panel NEXO OBRA · Parte diario · «Avance por dron» ──► estado por elemento + propuesta de metrado
```

## 1. Planificar el vuelo

```bash
python planificador_dron.py --lat <lat> --lon <lon> --ancho 25 --largo 30 --altura 40 --altura-edif 22
```
Salidas: `plan_vuelo.png`, `waypoints_litchi.csv` (nadir), `waypoints_litchi_oblicua.csv` (−60°), `plan_vuelo.kml`
(revisar en Google Earth) y `resumen_plan.json` (GSD, fotos, minutos, baterías).

- El Mini 5 Pro **no tiene SDK**: solo vuela misiones con DJI Fly. Importar el CSV en Litchi Hub → exportar KMZ → abrirlo en
  DJI Fly › Waypoints. Las órbitas no existen en el motor de a bordo: volarlas a mano (foto cada ~10°).
- Altura mínima = estructura + 15 m. Respetar las reglas de la DGAC y tener permiso del dueño de la obra.

## 2. Puntos de control (sin RTK son obligatorios)

Marcar 5–6 dianas en **puntos que existan en el modelo** (cruces de ejes A-1, A-5, D-1…, esquinas de losa) y medirlas.
Así la nube sale en las coordenadas del proyecto y el ICP del sistema solo corrige centímetros.

## 3. Procesar

WebODM con las fotos + archivo GCP → `odm_georeferencing/odm_georeferenced_model.laz`.
Exportar a `.ply` si no se instala `laspy` (CloudCompare: *Save as* PLY binario). Submuestrear a 3–5 cm si pesa > 400 MB.
Para Revit: importar el `.laz`/`.e57` en ReCap → `.rcp` → Insertar › Nube de puntos.

## 4. Sin vuelo todavía: nube simulada desde el IFC

```bash
python3 7_Dron/nube_desde_ifc.py --ifc REP04-CIT-XX-XX-M3-E-00001-R02.ifc --fecha 2027-09-30 --salida vuelo_simulado.ply
```
Sale en coordenadas compartidas/UTM (doble precisión), con color y efectos de fotogrametría, más `vuelo_simulado.verdad.json`.

## 5. Comparar con el modelo

Panel → **Parte diario → Avance por dron** → subir primero el `.ifc` (georreferencia) → elegir fecha y la nube → *Procesar archivo*.
Sin vuelo todavía: *Probar con nube sintética* genera una nube desde el modelo con verdad conocida.
Detalle técnico y métricas: `nexo-ia/README.md` (sección «Avance por dron») y `nexo-ia/pruebas/evaluar_escaneo.py`.
