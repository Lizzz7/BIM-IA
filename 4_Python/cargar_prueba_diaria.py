"""PRUEBA: registra metrados DIARIOS de prueba en el panel (archivo registros_<modelo>.json, no en Revit),
siguiendo el cronograma hasta una fecha de corte, con RETRASOS intencionales para ver alertas e indicadores.

Retrasos simulados (solo prueba):
  * EXC2 (excavación capa 2): empieza 3 días laborables tarde y avanza al 80 % del ritmo programado.
  * ANC2 (anclajes fila 2): empieza 4 días tarde y avanza al 70 %.
  * MUA2 (muros anclados del sótano 1): 1 de cada 3 elementos queda SIN ejecutar (atrasados); el resto, 5 días tarde.
  * TEN1 y el resto del anillo 1: según programa.
Cada día laborable registra la parte programada de ese día (1 / duración de la actividad).

Uso: python cargar_prueba_diaria.py 2027-03-20 [--simular]
Para borrar la prueba: eliminar 3_Modelo_y_parametros\\registros_<modelo>.json (y la carpeta respaldos_registros).
"""
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).parent.parent
corte = date.fromisoformat(sys.argv[1]); simular = "--simular" in sys.argv
crono = json.loads((RAIZ / "1_Panel" / "datos" / "nexo_no_datos.json").read_text(encoding="utf-8"))
pr = json.loads((RAIZ / "3_Modelo_y_parametros" / f"parametros_revit_{crono['proyecto']['modelo']}.json").read_text(encoding="utf-8"))
FER = {date.fromisoformat(f) for f in crono["proyecto"]["calendario"]["feriados"]}
lab = lambda d: d.weekday() != 6 and d not in FER
RETRASO = {"EXC2": (3, 0.80), "ANC2": (4, 0.70), "MUA2": (5, 1.0)}      # días de retraso, ritmo


def dias_lab(ini, n):
    """n días laborables desde ini (incluido)."""
    out, d = [], ini
    while len(out) < n:
        if lab(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def mover(d, k):
    while k > 0:
        d += timedelta(days=1); k -= lab(d)
    return d


con_elementos = {p["item"] for e in pr["elementos"] for p in e["partidas"]}
el_de_act = defaultdict(list)
for e in pr["elementos"]:
    for p in e["partidas"]:
        a = e["actividad"] if p["clase"] in ("concreto", "muro") else e["act_encofrado"] if p["clase"] == "encofrado" else e["act_acero"]
        el_de_act[a].append((e, p))
pendientes = {e["id"] for i, e in enumerate(sorted({e["id"]: e for e, _ in el_de_act["MUA2"]}.values(), key=lambda e: e["id"])) if i % 3 == 0}

regs = defaultdict(list)          # fecha -> registros
for a in crono["actividades"]:
    if a["tipo"] == "GLO":
        ini = date.fromisoformat(a["inicio"])
    else:
        ini = date.fromisoformat(a["inicio"])
    lag, ritmo = RETRASO.get(a["id"], (0, 1.0))
    dias = dias_lab(mover(ini, lag) if lag else ini, a["duracion"])
    dias = [d for d in dias if d <= corte]
    if not dias:
        continue
    f = ritmo / a["duracion"]          # fracción por día
    for d in dias:
        k = d.isoformat()
        for p in a["partidas"]:
            if p["item"] not in con_elementos:
                regs[k].append({"id": 0, "item": p["item"], "cantidad": round(p["metrado"] * f, 6)})
        for e, p in el_de_act[a["id"]]:
            if a["id"] == "MUA2" and e["id"] in pendientes:
                continue
            regs[k].append({"id": e["id"], "item": p["item"], "cantidad": round(p["metrado"] * f, 6)})

n = sum(len(v) for v in regs.values())
print(f"Prueba hasta {corte}: {n} registros en {len(regs)} días · elementos de MUA2 sin ejecutar: {len(pendientes)} · simular={simular}")
ok = rech = 0
for k in sorted(regs):
    cuerpo = json.dumps({"fecha": k, "simular": simular, "registros": regs[k]}).encode()
    req = urllib.request.Request("http://127.0.0.1:8770/api/metrado", data=cuerpo, method="POST", headers={"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    ok += len(r["aplicados"]); rech += len(r["rechazados"])
    if r["rechazados"]:
        print("  rechazados", k, r["rechazados"][:2])
print(f"Aplicados {ok} · rechazados {rech}")
