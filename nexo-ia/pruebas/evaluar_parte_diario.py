"""Evalúa el intérprete del parte diario contra casos con respuesta conocida.

Mide a nivel de REGISTRO (elemento, partida): precisión, exhaustividad y F1, y el error en S/ del parte.
Uso:  python3 pruebas/evaluar_parte_diario.py            (intérprete por reglas)
      NEXO_LLM=ollama python3 pruebas/evaluar_parte_diario.py   (con LLM; compara contra reglas)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("NEXO_ESTADO", "/tmp/nexo_eval")
from nexo_ia import datos as D, llm, parte_diario as P  # noqa: E402


def claves(intencion):
    r = P.resolver({"trabajos": intencion})
    return {(x["id"], x["item"]): x["cantidad"] for x in r["registros"]}


def evaluar(usar_llm):
    casos = json.loads((Path(__file__).parent / "casos_parte_diario.json").read_text(encoding="utf-8"))["casos"]
    tp = fp = fn = 0
    err_soles, filas = 0.0, []
    for c in casos:
        out = P.procesar(c["texto"], "2027-06-10", usar_llm=usar_llm)
        esp, obt = claves(c["esperado"]), {(x["id"], x["item"]): x["cantidad"] for x in out["registros"]}
        a, b = set(esp), set(obt)
        tp, fp, fn = tp + len(a & b), fp + len(b - a), fn + len(a - b)
        s_esp = sum(q * D.partidas()[k[1]]["pu"] for k, q in esp.items())
        s_obt = sum(q * D.partidas()[k[1]]["pu"] for k, q in obt.items())
        err_soles += abs(s_esp - s_obt)
        ok = a == b
        filas.append((("✔" if ok else "✘"), c["texto"][:70], len(a), len(b), round(s_esp - s_obt, 2)))
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    exactos = sum(f[0] == "✔" for f in filas)
    return {"interprete": (llm.PROVEEDOR + ":" + llm.MODELO) if usar_llm and llm.disponible() else "reglas",
            "casos": len(casos), "casos_exactos": exactos, "precision": round(p, 3), "exhaustividad": round(r, 3),
            "f1": round(f1, 3), "error_absoluto_soles": round(err_soles, 2), "detalle": filas}


if __name__ == "__main__":
    modos = [False] + ([True] if llm.disponible() else [])
    for m in modos:
        r = evaluar(m)
        print(f"\n=== {r['interprete']} · {r['casos_exactos']}/{r['casos']} casos exactos · P={r['precision']} R={r['exhaustividad']} "
              f"F1={r['f1']} · error S/ {r['error_absoluto_soles']:,.2f}")
        for f in r["detalle"]:
            print(f"  {f[0]} {f[1]:<70}  esperado {f[2]:>3} reg · obtenido {f[3]:>3} reg · Δ S/ {f[4]:,.2f}")
