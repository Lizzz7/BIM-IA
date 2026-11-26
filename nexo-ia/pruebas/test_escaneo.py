"""Pruebas del avance por dron (Scan-vs-BIM). Uso: python3 pruebas/test_escaneo.py  (o python3 -m pytest pruebas -q)
Usa carpetas temporales: no toca el repo ni estado/."""
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="nexo_escaneo_"))
os.environ["NEXO_ESTADO"] = str(TMP / "estado")
os.environ["NEXO_MODELOS"] = str(TMP / "modelos")
sys.path.insert(0, str(AQUI))

from nexo_ia import datos as D, escaneo as X, nube_io, sintetico as S  # noqa: E402
import servidor  # noqa: E402

D.usar()


def test_lectura_de_nubes():
    P = np.random.default_rng(0).normal(size=(5000, 3))
    nube_io.escribir_ply(TMP / "a.ply", P)
    assert np.allclose(nube_io.leer(TMP / "a.ply"), P, atol=1e-5)
    (TMP / "a.xyz").write_text("// x y z\n" + "\n".join(f"{x} {y} {z} 120 120 120" for x, y, z in P[:100]))
    assert np.allclose(nube_io.leer(TMP / "a.xyz"), P[:100])
    (TMP / "a.ply2").write_bytes(b"ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\nproperty float y\nproperty float z\nend_header\n1 2 3\n4 5 6\n")
    assert nube_io.leer((TMP / "a.ply2").read_bytes(), "x.ply").tolist() == [[1, 2, 3], [4, 5, 6]]


def test_icp_recupera_desalineacion():
    ref = X.referencia()["P"]
    dst = nube_io.submuestrear(ref, 0.3)
    a = np.radians(0.7)
    R = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    src = dst @ R.T + [0.25, -0.18, 0.05]
    T, rmse, _ = X.icp(src, dst)
    assert np.abs(X.aplicar(T, src) - dst).max() < 0.01 and rmse < 0.01


def test_escaneo_sintetico_acierta_y_alerta():
    nube, verdad, _ = S.generar("2027-06-30", semilla=7)
    r = X.procesar(nube, "2027-06-30", "prueba", verdad=verdad)
    m = r["metricas"]
    assert m["exactitud"] >= 0.97 and m["precision_construido"] >= 0.95 and m["exhaustividad_construido"] >= 0.95
    assert m["alertas_valorizacion"]["detectadas"] == m["alertas_valorizacion"]["sembradas"] == 2
    assert m["error_alineacion"]["traslacion_m"] < 0.03
    # la propuesta pasa las validaciones del propio sistema (mismas que el complemento de Revit)
    sim = servidor.registrar({"fecha": "2027-06-30", "simular": True, "registros": r["registros"]})
    assert r["registros"] and not sim["rechazados"] and not sim["alertas"]
    # lo construido por el dron nunca supera el saldo de cada elemento
    ej = D.ejecutado_por_elemento()
    for x in r["registros"]:
        p = next(p for p in D.elementos()[x["id"]]["partidas"] if p["item"] == x["item"])
        assert x["cantidad"] <= p["metrado"] - ej.get(x["id"], {}).get(x["item"], 0) + 1e-6


if __name__ == "__main__":
    fallos = 0
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            try:
                f(); print(f"✔ {nombre}")
            except Exception as ex:  # noqa: BLE001
                fallos += 1; print(f"✘ {nombre}: {type(ex).__name__}: {ex}")
    sys.exit(1 if fallos else 0)
