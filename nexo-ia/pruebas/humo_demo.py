"""Prueba de humo de la demo por HTTP: levanta el servidor real en un puerto libre con estado temporal y recorre
la cadena completa  punto → elemento → partida → metrado → S/ → alerta → valorización.

Uso:  python3 pruebas/humo_demo.py            (≈1–2 min; incluye la simulación paso a paso)
      python3 pruebas/humo_demo.py --rapido   (sin la simulación)
No toca estado/ ni el repo."""
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

AQUI = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="nexo_humo_"))
os.environ["NEXO_ESTADO"] = str(TMP / "estado")
os.environ["NEXO_MODELOS"] = str(TMP / "modelos")
sys.path.insert(0, str(AQUI))
import servidor  # noqa: E402

srv = ThreadingHTTPServer(("127.0.0.1", 0), servidor.Manejador)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def pide(ruta, cuerpo=None, crudo=False):
    req = urllib.request.Request(BASE + ruta, data=None if cuerpo is None else json.dumps(cuerpo).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if cuerpo is None else "POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        b = r.read()
        return b if crudo else json.loads(b)


def paso(nombre, f):
    t = time.time()
    r = f()
    print(f"✔ {nombre}  ({time.time() - t:.1f}s){'  · ' + r if isinstance(r, str) else ''}")


def main():
    corte = "2027-06-30"
    paso("panel con la IA inyectada", lambda: None if b"/ia/nexo_ia.js" in pide("/", crudo=True) else (_ for _ in ()).throw(AssertionError("sin inyección")))
    c0 = pide(f"/api/ia/costos?corte={corte}")
    paso("costos al corte", lambda: f"presupuesto S/ {c0['presupuesto']['bruta']:,.2f} · valorizado S/ {c0['valorizado']:,.2f} · SPI {c0['spi']}")
    r = pide("/api/ia/parte", {"texto": "¿Cuánto llevamos valorizado?", "corte": corte})
    assert r["tipo"] == "consulta" and r["cifras"]
    paso("chat: pregunta de costos", lambda: r["texto"][:90] + "…")
    p = pide("/api/ia/parte", {"texto": "Vaciamos las columnas del 2do piso, lado A", "fecha": corte})
    assert p["tipo"] == "parte" and p["registros"]
    sim = pide("/api/metrado", {"fecha": corte, "simular": True, "registros": p["registros"]})
    assert sim["simulado"] and not sim["rechazados"]
    paso("chat: parte diario → metrado validado", lambda: f"{len(p['registros'])} valores · S/ {p['monto_total']:,.2f}")
    d = pide("/api/ia/escaneo/demo", {"fecha": corte})                      # punto → elemento → partida (guarda, como el botón)
    assert d["metricas"]["alertas_valorizacion"]["detectadas"] == d["metricas"]["alertas_valorizacion"]["sembradas"]
    paso("dron: nube sintética → elementos → propuesta", lambda: f"avance {d['avance']['total']['avance_pct']} % · propone S/ {d['monto_total']:,.2f} · "
         f"{len(d['alertas_valorizacion'])} alertas · exactitud {d['metricas']['exactitud']}")
    a = pide("/api/ia/auditoria")
    d01 = [h for h in a["hallazgos"] if h["regla"] == "D01"]
    assert len(d01) == len(d["alertas_valorizacion"]) and all(h["impacto_soles"] > 0 for h in d01)
    paso("alerta del dron en la auditoría (D01)", lambda: f"{len(d01)} hallazgos · S/ {sum(h['impacto_soles'] for h in d01):,.2f}")
    c1 = pide(f"/api/ia/costos?corte={corte}")
    assert c1["dron"] and c1["dron"]["en_riesgo"] > 0 and c1["neto_recomendado"] < c1["valorizado"]
    paso("costos con el dron", lambda: f"en riesgo S/ {c1['dron']['en_riesgo']:,.2f} · por valorizar S/ {c1['dron']['por_valorizar']:,.2f}")
    reg = pide("/api/metrado", {"fecha": corte, "registros": d["registros"], "origen": "ia-dron"})
    assert reg["guardado"] and not reg["rechazados"]
    c2 = pide(f"/api/ia/costos?corte={corte}")
    assert abs(c2["valorizado"] - (c1["valorizado"] + reg["monto_cd"])) < 0.05
    paso("registrar la propuesta → valorización", lambda: f"+S/ {reg['monto_cd']:,.2f} · valorizado S/ {c2['valorizado']:,.2f} · SPI {c2['spi']}")
    z = zipfile.ZipFile(io.BytesIO(pide("/api/ia/export/powerbi.zip", crudo=True)))
    assert "fact_registros.csv" in z.namelist() and "fact_dron_elementos.csv" in z.namelist()
    paso("export Power BI", lambda: f"{len(z.namelist())} archivos")
    h = pide("/api/ia/escaneo/historial")["escaneos"]
    assert len(h) == 1
    paso("historial de escaneos", lambda: f"{len(h)} escaneo(s)")
    if "--rapido" not in sys.argv:
        antes = (TMP / "estado").glob("**/*")
        antes = {str(x): x.stat().st_mtime_ns for x in antes if x.is_file()}
        s = pide("/api/ia/simulacion", {"corte": corte})
        despues = {str(x): x.stat().st_mtime_ns for x in (TMP / "estado").glob("**/*") if x.is_file()}
        assert s["guardado"] is False and len(s["pasos"]) == 7 and antes == despues
        paso("simulación paso a paso (no guardó nada)", lambda: s["pasos"][6]["datos"]["conclusion"][:110] + "…")
        m = pide(f"/api/ia/simulacion/etapas?corte={corte}")
        b = pide(f"/api/ia/simulacion/etapas.bin?corte={corte}", crudo=True)
        assert len(b) == 4 + 18 * m["puntos"] and antes == {str(x): x.stat().st_mtime_ns for x in (TMP / "estado").glob("**/*") if x.is_file()}
        paso("la obra construyéndose (nube por etapas)", lambda: f"{m['puntos']:,} puntos en {m['dia_fin']} días de obra (corte el día {m['dia_corte']}) · {len(m['elementos'])} elementos")
    print("\nCadena completa OK.")


if __name__ == "__main__":
    try:
        main()
    finally:
        srv.shutdown()
        shutil.rmtree(TMP, ignore_errors=True)
