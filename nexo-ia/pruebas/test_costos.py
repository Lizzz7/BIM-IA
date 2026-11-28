"""Costos y presupuesto, alertas del dron en el auditor, simulación sin escritura y export Power BI.
Uso: python3 pruebas/test_costos.py   (o python3 -m pytest pruebas -q). Usa carpetas temporales: no toca estado/."""
import csv
import io
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="nexo_costos_"))
os.environ["NEXO_ESTADO"] = str(TMP / "estado")
os.environ["NEXO_MODELOS"] = str(TMP / "modelos")
sys.path.insert(0, str(AQUI))

from nexo_ia import auditor, costos, escaneo, exportar, metrado, simulacion  # noqa: E402
from nexo_ia import datos as D  # noqa: E402

D.usar()


def test_programado_igual_al_panel():
    # valores calculados con pvA() del propio panel (1_Panel/index.html) ejecutado en node
    for f, v in {"2027-03-20": 509505.6888, "2027-06-30": 1292827.7837, "2027-09-15": 1984636.1296}.items():
        assert abs(costos.pv(f) - v) < 0.01, (f, costos.pv(f), v)


def test_presupuesto_valorizado_y_pie_como_el_panel():
    assert costos.bac() == costos.r2(sum(costos.r2(p["metrado"] * p["pu"]) for p in D.partidas().values()))
    v = costos.valorizacion(100000)                                  # pie del repo: GG 12 %, UT 8 %, IGV 18 %
    assert (v["gg"], v["ut"], v["subtotal"], v["igv"], v["bruta"]) == (12000, 8000, 120000, 21600, 141600)
    assert costos.r2(0.125) == 0.13 and costos.r2(-0.125) == -0.13   # redondeo S10 del panel (no bancario)
    reg = D.leer_registros()
    a_mano = sum(q * D.partidas()[it]["pu"] for k, n in reg["elementos"].items() if int(k) in D.elementos()
                 for _, it, q in D.parsear(n["registro"])) + sum(q * D.partidas()[it]["pu"] for _, it, q in D.parsear(reg["global"]))
    assert abs(costos.ev() - a_mano) < 1e-6
    r = costos.resumen("2027-06-30")
    assert abs(sum(c["presupuesto"] for c in r["por_capitulo"]) - r["presupuesto"]["cd"]) < 1
    assert r["modelo"]["cd_modelo"] + r["modelo"]["cd_global"] - r["presupuesto"]["cd"] < 1


def _vacio():
    return {"elementos": {}, "global": ""}


def test_r04_mayor_metrado_y_r05_secuencia():
    en_disco = (D.ruta_registros()).read_text()
    e = next(x for x in D.elementos().values() if any(p["clase"] == "concreto" for p in x["partidas"]))
    p = next(p for p in e["partidas"] if p["clase"] == "concreto")
    reg, r = metrado.aplicar(_vacio(), {"fecha": "2027-06-10", "registros": [{"id": e["id"], "item": p["item"], "cantidad": p["metrado"] * 1.2}]})
    assert r["alertas"], "el complemento alerta mayor metrado"
    with D.simulando(reg):
        h = [x for x in auditor.auditar(incluir_ml=False)["hallazgos"] if x["regla"] == "R04"]
    assert h and abs(h[0]["impacto_soles"] - 0.2 * p["metrado"] * D.partidas()[p["item"]]["pu"]) < 0.02
    # R05: avance de una actividad cuya predecesora (con elementos) no tiene avance
    ape, acts = D.actividades_por_elemento(), {a["id"]: a for a in D.cronograma()["actividades"]}
    con_el = {a for v in ape.values() for a in v.values()}
    eid, act = next((i, v["concreto"]) for i, v in ape.items() if i in D.elementos()
                    and any(pr in con_el for pr in acts.get(v["concreto"], {}).get("predecesoras", [])))
    it = next(p["item"] for p in D.elementos()[eid]["partidas"] if p["clase"] == "concreto")
    reg, _ = metrado.aplicar(_vacio(), {"fecha": "2027-02-01", "registros": [{"id": eid, "item": it, "cantidad": 0.01}]})
    with D.simulando(reg):
        assert any(x["regla"] == "R05" and x["evidencia"]["valores"]["actividad"] == act for x in auditor.auditar(incluir_ml=False)["hallazgos"])
    assert D.ruta_registros().read_text() == en_disco, "aplicar()/simulando() no escriben registros.json"


def test_d01_alerta_del_dron_entra_al_auditor_con_su_monto():
    reg = D.leer_registros()
    k, n = next((k, n) for k, n in reg["elementos"].items() if int(k) in D.elementos() and D.parsear(n["registro"]))
    monto = sum(q * D.partidas()[it]["pu"] for _, it, q in D.parsear(n["registro"]))
    falso = {"fecha": "2027-06-30", "nombre": "prueba", "elementos": [], "alertas_secuencia": [],
             "alertas_valorizacion": [{"id": int(k), "estado": "no_construido", "severidad": "alta", "visible": 0.9, "cobertura_visible": 0.01}]}
    tok = escaneo._ultimo_sim.set(falso)
    try:
        h = [x for x in auditor.auditar(incluir_ml=False)["hallazgos"] if x["regla"] == "D01"]
        c = costos.resumen("2027-06-30", escaneo_ultimo=falso)
    finally:
        escaneo._ultimo_sim.reset(tok)
    assert len(h) == 1 and abs(h[0]["impacto_soles"] - monto) < 0.01 and h[0]["severidad"] == "alta"
    assert abs(c["dron"]["en_riesgo"] - monto) < 0.01 and abs(c["neto_recomendado"] - (c["valorizado"] - c["dron"]["en_riesgo"])) < 0.02


def _foto():
    d = D.estado()
    return {str(p.relative_to(d)): (p.stat().st_size, p.stat().st_mtime_ns) for p in d.rglob("*") if p.is_file()}


def test_simulacion_no_guarda_nada_y_cuadra():
    auditor.auditar()                                                # caché del ML ya creada (no cuenta como escritura)
    antes = _foto()
    r = simulacion.simular("2027-06-30", semilla=7)
    assert _foto() == antes, "la simulación escribió en estado/"
    p = {x["n"]: x["datos"] for x in r["pasos"]}
    assert len(r["pasos"]) == 7 and r["guardado"] is False
    assert abs(sum(f["monto"] for f in p[3]["partidas"]) - p[5]["propuesta"]["cd"]) < 0.05
    assert p[4]["aceptados"] == p[4]["valores"] and not p[4]["alertas_mayor_metrado"]
    assert set(p[6]["detectadas"]) == set(p[6]["sembradas"]) and p[6]["en_riesgo"] > 0
    assert any(h["regla"] == "D01" for h in p[6]["hallazgos"])
    assert abs(p[7]["despues"]["valorizado"] - (p[7]["antes"]["valorizado"] + p[5]["propuesta"]["cd"])) < 0.05
    # la obra construyéndose: nube por etapas, también solo en memoria
    import numpy as np
    meta, b = simulacion.etapas("2027-06-30", semilla=7)
    assert _foto() == antes, "la nube por etapas escribió en estado/"
    n = int(np.frombuffer(b, np.uint32, 1)[0])
    assert len(b) == 4 + 18 * n and n == meta["puntos"] and 0 < n <= 450_000
    dia = np.frombuffer(b[4 + 15 * n:4 + 17 * n], np.uint16)
    tipo = np.frombuffer(b[4 + 17 * n:], np.uint8)
    assert dia.max() == meta["dia_fin"] and len(np.unique(dia[tipo == 0])) > 30, "el edificio se construye en muchas fechas"
    assert len(meta["elementos"]) == len(D.elementos()) and 0 < meta["dia_corte"] < meta["dia_fin"]
    assert (tipo == 0).mean() > 0.9, "casi todos los puntos son estructura (sin grúa, material ni vecinos)"
    from datetime import date, timedelta
    sem = meta["programado_semanal"][10]
    assert abs(sem["programado"] - costos.pv((date.fromisoformat(meta["inicio"]) + timedelta(days=sem["dia"])).isoformat())) < 0.01


def test_export_powerbi():
    z = zipfile.ZipFile(io.BytesIO(exportar.zip_powerbi(auditor.auditar(incluir_ml=False))))
    nombres = set(z.namelist())
    for t in ("dim_partidas", "dim_elementos", "dim_periodos", "dim_parametros", "fact_registros", "fact_hallazgos",
              "fact_hallazgo_elemento", "fact_dron_elementos", "fact_escaneos"):
        assert f"{t}.csv" in nombres, t
    assert "LEEME_PowerBI.md" in nombres
    filas = list(csv.DictReader(io.StringIO(z.read("fact_registros.csv").decode("utf-8-sig"))))
    assert abs(sum(float(f["monto_cd"]) for f in filas) - costos.ev()) < 0.05
    part = list(csv.DictReader(io.StringIO(z.read("dim_partidas.csv").decode("utf-8-sig"))))
    assert abs(sum(float(f["monto_cd"]) for f in part) - costos.bac()) < 1
    assert json.loads(z.read("costos_resumen.json"))["presupuesto"]["cd"] == costos.bac()


if __name__ == "__main__":
    fallos = 0
    try:
        for n, f in list(globals().items()):
            if n.startswith("test_"):
                t = time.time()
                try:
                    f(); print(f"ok  {n}  ({time.time() - t:.1f}s)")
                except Exception as ex:  # noqa: BLE001
                    fallos += 1; print(f"FALLA  {n}: {type(ex).__name__}: {ex}")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if fallos else 0)
