"""Evalúa el comparador Scan-vs-BIM (avance por dron) contra nubes SINTÉTICAS con verdad conocida.

Para cada escenario genera una nube desde el modelo del repo (fecha de corte, ruido, oclusión, desalineación),
la pasa por escaneo.procesar() y mide:
  - exactitud / precisión / exhaustividad de "construido" sobre los elementos que el sistema decide
  - cuántos quedan sin decidir (no observables o dudosos): el sistema los marca para revisión, no adivina
  - alertas de valorización sembradas (registrado pero no construido) detectadas
  - error de la alineación ICP frente a la desalineación aplicada
Uso:  python3 pruebas/evaluar_escaneo.py            (todos los escenarios, ~1 min)
      python3 pruebas/evaluar_escaneo.py --rapido   (uno solo)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("NEXO_ESTADO", "/tmp/nexo_eval_escaneo")
from nexo_ia import datos as D, escaneo as X, sintetico as S  # noqa: E402

ESCENARIOS = [
    {"nombre": "Fin de mes 3 (sótanos)", "fecha_corte": "2027-03-31"},
    {"nombre": "Fin de mes 6 (base)", "fecha_corte": "2027-06-30"},
    {"nombre": "Fin de mes 6 · ruido 4 cm, 30 % huecos", "fecha_corte": "2027-06-30", "ruido": 0.04, "huecos": 0.30, "semilla": 11},
    {"nombre": "Fin de mes 9 (casco alto)", "fecha_corte": "2027-09-30"},
    {"nombre": "Fin de mes 9 · sin oclusión (cota superior)", "fecha_corte": "2027-09-30", "oclusion": False},
    {"nombre": "Fin de mes 6 · sin alinear (control)", "fecha_corte": "2027-06-30", "_alinear": False},
]


def correr(esc):
    p = {k: v for k, v in esc.items() if not k.startswith("_") and k != "nombre"}
    nube, verdad, _, _ = S.generar(**p)
    r = X.procesar(nube, verdad["fecha_corte"], esc["nombre"], verdad=verdad, alinear=esc.get("_alinear", True))
    m = r["metricas"]
    return {"escenario": esc["nombre"], "puntos": verdad["puntos"], "construidos_reales": len(verdad["construidos"]),
            "construidos_ocultos": len(verdad["construidos_invisibles"]), "exactitud": m["exactitud"],
            "precision": m["precision_construido"], "exhaustividad": m["exhaustividad_construido"],
            "decididos": m["decididos"], "sin_decidir": m["sin_decidir"], "matriz": m["matriz"],
            "alertas": m.get("alertas_valorizacion"), "error_alineacion": m.get("error_alineacion"),
            "avance_pct": r["avance"]["total"]["avance_pct"], "monto_propuesto": r["monto_total"], "segundos": r["segundos"],
            "errores": m["errores"][:5]}


if __name__ == "__main__":
    D.usar()
    escs = ESCENARIOS[1:2] if "--rapido" in sys.argv else ESCENARIOS
    filas = [correr(e) for e in escs]
    print(f"\n{'Escenario':<46} {'exact.':>7} {'prec.':>6} {'exh.':>6} {'decid.':>7} {'sin decidir':>12} {'alertas':>8} {'ICP (m / °)':>14}")
    for f in filas:
        sd = f["sin_decidir"]; al = f["alertas"] or {}; ea = f["error_alineacion"] or {}
        print(f"{f['escenario']:<46} {f['exactitud']*100:6.1f}% {f['precision']*100:5.1f}% {f['exhaustividad']*100:5.1f}% "
              f"{f['decididos']:>7} {sd['construido']:>5}c/{sd['no_construido']:>4}n {al.get('detectadas', 0)}/{al.get('sembradas', 0):<6} "
              f"{(str(ea.get('traslacion_m', '—')) + ' / ' + str(ea.get('giro_grados', '—'))):>14}")
        for e in f["errores"]:
            print(f"      ✘ {e['id']} {e['grupo']} {e['nivel']}: real {e['real']}, sistema {e['estado']} "
                  f"(visible {e['visible']*100:.0f} %, cubierto {e['cobertura_visible']*100:.0f} %)")
    salida = Path(__file__).parent / "resultado_evaluacion_escaneo.json"
    salida.write_text(json.dumps(filas, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nDetalle: {salida}")
