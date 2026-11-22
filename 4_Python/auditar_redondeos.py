"""Auditoría de decimales del presupuesto (Excel S10 v2) y del panel. Solo lectura.

Mide, partida por partida, cuánto cambia el monto por cada redondeo:
  1. metrado del modelo -> metrado del presupuesto (2 decimales)
  2. metrados que dependen de otros ya redondeados (acero = concreto redondeado x cuantía; ladrillo; curado)
  3. precio unitario: líneas del APU redondeadas (cantidad 4 dec., parcial 2 dec., hh 2 dec.) y P.U. a 2 decimales
  4. parcial = ROUND(metrado x P.U., 2)
  5. redondear cada elemento a 2 decimales antes de sumar (lo que hace una tabla de Revit / Power BI)
  6. panel: metrado repartido en elementos (4 decimales) frente al metrado del presupuesto
Uso: python auditar_redondeos.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).parent.parent
XLS = RAIZ / "5_Documentacion" / "Presupuesto_Estructuras_REP0-MOD2-R02_v3.xlsx"
wb = load_workbook(XLS, data_only=True)
P, A, I, H, Sup = (wb[n] for n in ("Presupuesto", "Análisis de Precios Unitarios", "Precios y Cantidades Recursos", "Hoja de Metrados", "Supuestos y Fuentes"))

# ---------- presupuesto
part = {}
for r in range(11, P.max_row + 1):
    it, de, un, me, pu, pa = (P.cell(r, c).value for c in range(1, 7))
    if isinstance(it, str) and un:
        part[it] = {"desc": de, "und": un, "met": me, "pu": pu, "parcial": pa}
cd_excel = next(P.cell(r, 6).value for r in range(11, P.max_row + 1) if P.cell(r, 2).value == "Costo Directo")

# ---------- hoja de metrados: total con más decimales (suma de líneas a 4 dec.)
met_hm = {}
for r in range(6, H.max_row + 1):
    it, tot = H.cell(r, 1).value, H.cell(r, 6).value
    if isinstance(it, str) and it in part and isinstance(tot, (int, float)):
        met_hm[it] = tot

# ---------- precios de insumos y hh sin redondear
precio = {I.cell(r, 1).value: I.cell(r, 5).value for r in range(8, I.max_row + 1) if isinstance(I.cell(r, 1).value, str) and isinstance(I.cell(r, 5).value, (int, float))}
hh_exacto = {}
for r in range(6, 9):
    nom, costo_dia, hh = Sup.cell(r, 1).value, Sup.cell(r, 6).value, Sup.cell(r, 7).value
    cod = {"OPERARIO": "0147010002", "OFICIAL": "0147010003", "PEON": "0147010004"}[nom]
    hh_exacto[cod] = costo_dia / 8
her_pct = next(Sup.cell(r, 4).value for r in range(1, 40) if str(Sup.cell(r, 1).value).startswith("Herramientas manuales"))

# ---------- APU: precio unitario exacto (sin redondear líneas) vs el del Excel
cu = {}
item = rend = None
for r in range(1, A.max_row + 1):
    a0, b0 = A.cell(r, 1).value, A.cell(r, 2).value
    if a0 == "Partida":
        item = b0.split()[0]; cu[item] = {"excel": None, "mo": 0.0, "resto": 0.0}
    elif a0 == "Rendimiento" and item:
        rend = A.cell(r, 4).value; cu[item]["excel"] = A.cell(r, 7).value
    elif item and isinstance(a0, str) and len(a0) == 10 and a0.isdigit():
        cuad, cant = A.cell(r, 4).value, A.cell(r, 5).value
        if a0 == "0337010001":
            continue
        q = cuad * 8 / rend if isinstance(cuad, (int, float)) else cant
        p = hh_exacto.get(a0, precio.get(a0, 0))
        if a0.startswith("0147"):
            cu[item]["mo"] += q * p
        else:
            cu[item]["resto"] += q * p
for it, c in cu.items():
    c["exacto"] = c["mo"] * (1 + her_pct) + c["resto"]

# ---------- metrados exactos desde el modelo (para partidas que dependen de otras ya redondeadas)
import metrados as M
import presupuesto_s10 as PS
D, F, X = M.calcular(str(RAIZ / "3_Modelo_y_parametros" / "metrados_REP0-MOD2-R02.json"))
conc, enc, area = defaultdict(float), defaultdict(float), defaultdict(float)
for f in F:
    conc[(f["g"], f["fc"])] += f["conc"]; area[f["g"]] += f["area"]
    enc[f["g"]] += f["area"] if f["g"] == "ALI" else f["enc"]
cuantia = {g: v[6] for g, v in PS.GRUPOS.items()}
nombre_grupo = {v[0]: g for g, v in PS.GRUPOS.items()}

def exacto(it, d):
    """Metrado sin ningún redondeo intermedio (None si la partida no sale del modelo)."""
    du = d.upper()
    if du.startswith("ACERO DE REFUERZO") and " EN " in d:
        g = nombre_grupo.get(d.split(" EN ", 1)[1])
        if g:
            return sum(v for (gg, _), v in conc.items() if gg == g) * cuantia[g]
    if du.startswith("LADRILLO DE TECHO"):
        return area["ALI"] * M.LADRILLO_M2
    if du.startswith("CURADO"):
        return sum(enc.values())
    return met_hm.get(it)

# ---------- 5: redondear cada elemento a 2 decimales antes de sumar (tabla de Revit / Power BI)
por_elem = defaultdict(lambda: [0.0, 0.0])        # (grupo, f'c) -> [exacto, suma de elementos redondeados]
for f in F:
    k = (f["g"], f["fc"]); por_elem[k][0] += f["conc"]; por_elem[k][1] += round(f["conc"], 2)

# ---------- 6: panel (metrado de cada elemento con 4 decimales)
pr = json.loads((RAIZ / "3_Modelo_y_parametros" / "parametros_revit_REP0-MOD2-R02.json").read_text(encoding="utf-8"))
suma_panel = defaultdict(float)
for e in pr["elementos"]:
    for p in e["partidas"]:
        suma_panel[p["item"]] += p["metrado"]

filas = []
for it, p in part.items():
    ex_met = exacto(it, p["desc"])
    ex_cu = cu.get(it, {}).get("exacto")
    exacto_total = (ex_met if ex_met is not None else p["met"]) * (ex_cu if ex_cu is not None else p["pu"])
    d_met = ((ex_met - p["met"]) * p["pu"]) if ex_met is not None else 0.0
    d_pu = ((ex_cu - p["pu"]) * p["met"]) if ex_cu is not None else 0.0
    d_parc = p["parcial"] - p["met"] * p["pu"]
    panel = suma_panel.get(it)
    d_panel = ((panel - p["met"]) * p["pu"]) if panel is not None else None
    filas.append((it, p, ex_met, ex_cu, exacto_total, d_met, d_pu, d_parc, d_panel))

print(f"Costo directo Excel: {cd_excel:,.2f} | sin ningún redondeo: {sum(f[4] for f in filas):,.2f} | diferencia: {cd_excel - sum(f[4] for f in filas):,.2f}")
print(f"Suma de partidas del Excel (parciales): {sum(p['parcial'] for p in part.values()):,.2f}")
print()
print("Partidas con más efecto de redondeo (S/):")
print(f"{'Ítem':9} {'Und':4} {'Met. Excel':>12} {'Met. exacto':>13} {'PU Excel':>9} {'PU exacto':>11} {'Δ metrado':>10} {'Δ P.U.':>9} {'Δ parcial':>9} {'Total Δ':>9}")
for it, p, ex_met, ex_cu, tot, dm, dpu, dpa, dpan in sorted(filas, key=lambda f: -abs(f[1]["parcial"] - f[4]))[:18]:
    print(f"{it:9} {p['und']:4} {p['met']:12,.2f} {ex_met if ex_met is not None else float('nan'):13,.4f} {p['pu']:9,.2f} {ex_cu if ex_cu is not None else float('nan'):11,.4f} "
          f"{-dm:10,.2f} {-dpu:9,.2f} {dpa:9,.4f} {p['parcial'] - tot:9,.2f}")
print()
print("Redondear CADA ELEMENTO a 2 decimales antes de sumar (como una tabla de Revit o Power BI), concreto:")
for k, (ex, r2) in sorted(por_elem.items(), key=lambda kv: -abs(kv[1][1] - kv[1][0]))[:8]:
    print(f"  {k[0]:5} f'c={k[1]}  exacto {ex:10.4f} m3 · suma de redondeados {r2:10.2f} m3 · diferencia {r2 - ex:+.4f} m3")
print()
print("Panel: suma del metrado repartido en elementos frente al metrado del presupuesto:")
for it, p, *_, dpan in sorted(filas, key=lambda f: -abs(f[8] or 0))[:6]:
    if dpan is not None:
        print(f"  {it:9} presupuesto {p['met']:12,.2f} · elementos {suma_panel[it]:14,.4f} · Δ S/ {dpan:,.2f}")
