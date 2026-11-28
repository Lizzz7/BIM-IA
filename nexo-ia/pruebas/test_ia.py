"""Pruebas de la capa de IA y del servidor. Uso: python3 pruebas/test_ia.py   (o python3 -m pytest pruebas -q)
Necesita el repo BIM-IA al lado (o NEXO_REPO=/ruta). Usa carpetas temporales: no toca el repo ni estado/."""
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="nexo_prueba_"))
os.environ["NEXO_ESTADO"] = str(TMP / "estado")
os.environ["NEXO_MODELOS"] = str(TMP / "modelos")
sys.path.insert(0, str(AQUI))

from nexo_ia import auditor, llm, narrador, parte_diario as P, verificador  # noqa: E402
from nexo_ia import datos as D  # noqa: E402
import empaquetar_version  # noqa: E402
import servidor  # noqa: E402

REPO_ID = D._modelo_del_repo().id


def _registrar(registros, fecha="2027-06-10"):
    reg = D.leer_registros()
    for x in registros:
        n = reg["elementos"].setdefault(str(x["id"]), {"registro": "", "obs": ""})
        n["registro"] += f"{fecha}|{x['item']}|{x['cantidad']!r};"
    D.ruta_registros().write_text(json.dumps(reg), encoding="utf-8")


# ---------------------------------------------------------------- verificador
def test_verificador_acepta_y_rechaza():
    ev = {"volumen_m3": 0.634, "impacto": 286.35, "prob": 0.865}
    assert verificador.verificar("Se duplican 0.63 m³ (S/ 286.35), probabilidad 86.5 %", ev)["ok"]
    assert verificador.verificar("Partida 04.05.01 del 2027-03-08", ev)["ok"]
    r = verificador.verificar("Se duplican 0.80 m³ por S/ 1,500.00", ev)
    assert not r["ok"] and set(r["sin_respaldo"]) == {"0.80", "1,500.00"}


# ---------------------------------------------------------------- auditor + ML
def test_auditor_hallazgos_reales():
    D.usar(REPO_ID)
    r = auditor.auditar()
    assert {"R01", "R02", "R03", "R06", "ML1"} <= {h["regla"] for h in r["hallazgos"]}
    assert r["resumen"]["R01"]["n"] == 97 and abs(r["resumen"]["R01"]["impacto_soles"] - 1232.57) < 0.05
    assert r["modelos"]["ML1"]["exactitud"] > 0.95
    c2 = [h for h in r["hallazgos"] if h["regla"] == "ML1" and "C-2" in h["titulo"]]
    assert c2 and c2[0]["evidencia"]["valores"]["grupo_sugerido"] == "PLA"
    for h in r["hallazgos"]:
        assert h["evidencia"]["fuente"] and h["evidencia"]["formula"]


def test_ids_unicos_y_estables():
    D.usar(REPO_ID)
    a = [h["id"] for h in auditor.auditar()["hallazgos"]]
    assert len(a) == len(set(a)), "IDs de hallazgo repetidos"
    assert a == [h["id"] for h in auditor.auditar()["hallazgos"]], "IDs cambian entre recálculos"


# ---------------------------------------------------------------- LLM: verificación y caché
def _con_llm_falso(respuesta, demora=0.0):
    llamadas = [0]

    def chat(s, u, e):
        llamadas[0] += 1
        time.sleep(demora)
        return respuesta
    viejo = (llm.PROVEEDOR, llm._chat)
    llm.PROVEEDOR, llm._chat = "falso", chat
    return llamadas, lambda: setattr(llm, "PROVEEDOR", viejo[0]) or setattr(llm, "_chat", viejo[1])


def test_narrador_rechaza_alucinacion():
    D.usar(REPO_ID)
    h = next(x for x in auditor.auditar()["hallazgos"] if x["regla"] == "R01")
    _, restaurar = _con_llm_falso(json.dumps({"observacion": "Se duplican 9.99 m³ de concreto.", "accion": "Unir geometría.",
                                              "responsable": "Modelador BIM", "afecta_valorizacion": True}))
    try:
        out = narrador.narrar(h, forzar=True)
    finally:
        restaurar()
    assert out["origen"].startswith("plantilla (el LLM no pasó") and out["verificacion"]["ok"]


def test_narrador_acepta_llm_correcto():
    D.usar(REPO_ID)
    h = next(x for x in auditor.auditar()["hallazgos"] if x["regla"] == "R01")
    v = h["evidencia"]["valores"]["volumen_m3"]
    _, restaurar = _con_llm_falso(json.dumps({"observacion": f"Placa y losa no unidas: {v} m³ medidos dos veces.",
                                              "accion": "Unir geometría en Revit.", "responsable": "Modelador BIM", "afecta_valorizacion": True}))
    try:
        out = narrador.narrar(h, forzar=True)
    finally:
        restaurar()
    assert out["origen"] == "llm" and out["verificacion"]["ok"]


def test_una_sola_llamada_con_20_usuarios():
    D.usar(REPO_ID)
    h = [x for x in auditor.auditar()["hallazgos"] if x["regla"] == "R01"][7]
    llamadas, restaurar = _con_llm_falso(json.dumps({"observacion": "Solape sin unir.", "accion": "Unir geometría.",
                                                     "responsable": "Modelador BIM", "afecta_valorizacion": True}), demora=0.5)
    try:
        hilos = [threading.Thread(target=lambda: (D.usar(REPO_ID), narrador.narrar(h))) for _ in range(20)]
        [t.start() for t in hilos]
        [t.join() for t in hilos]
    finally:
        restaurar()
    assert llamadas[0] == 1, f"{llamadas[0]} llamadas al LLM"


# ---------------------------------------------------------------- parte diario
def test_porcentaje_sobre_total_y_tope_en_saldo():
    D.usar(REPO_ID)
    t = {"trabajos": [{"paquete": "T05", "sector": "B", "grupos": ["VIG"], "clase": "encofrado", "porcentaje": 50}]}
    total = sum(p["metrado"] for e in D.elementos().values() if e["paquete"] == "T05" and e["sector"] == "B" and e["grupo"] == "VIG"
                for p in e["partidas"] if p["clase"] == "encofrado")
    ej0 = sum(D.ejecutado_por_elemento().get(x["id"], {}).get(x["item"], 0) for x in P.resolver(t)["registros"])
    a = P.resolver(t)["registros"]
    _registrar(a)
    b = P.resolver(t)["registros"]
    _registrar(b)
    c = P.resolver(t)["registros"]
    q = lambda L: sum(x["cantidad"] for x in L)
    assert abs(q(a) - min(total * 0.5, total - ej0)) < 1e-6
    assert abs(q(a) + q(b) + q(c) - (total - ej0)) < 1e-6, "tres veces 50 % no debe pasar del total"


def test_niveles_desde_el_modelo():
    D.usar(REPO_ID)
    r = P.interpretar_reglas("Encofrado del techo del semisótano sector A")["trabajos"]
    assert r and r[0]["paquete"] == "T03" and "COL" not in r[0]["grupos"]
    r = P.interpretar_reglas("Vaciado de columnas del sótano 1")["trabajos"]
    assert r and r[0]["paquete"] == "T02"


def test_parte_diario_como_se_habla_en_obra():
    D.usar(REPO_ID)
    casos = {"Se vació la losa del 3er piso": ("T06", "ambos", "concreto"),
             "Encofrado de vigas segundo piso sector A al 50%": ("T05", "A", "encofrado"),
             "Vaciamos las columnas del 2do piso, lado A": ("T05", "A", "concreto"),
             "Vaciado de zapatas sector B": ("CIM", "B", "concreto")}
    for texto, (paq, sec, clase) in casos.items():
        t = P.interpretar_reglas(texto)["trabajos"]
        assert t and (t[0]["paquete"], t[0]["sector"], t[0]["clase"]) == (paq, sec, clase), (texto, t)


def test_parte_diario_sugiere_en_vez_de_no_entendi():
    D.usar(REPO_ID)
    r = P.interpretar_reglas("Vaciado de columnas")
    assert not r["trabajos"] and "nivel" in r["dudas"][0] and r["sugerencias"]
    s = P.interpretar_reglas(r["sugerencias"][0])["trabajos"]            # la sugerencia se puede registrar tal cual
    assert s and s[0]["grupos"] == ["COL"] and s[0]["clase"] == "concreto"
    assert P.interpretar_reglas("Llovió toda la mañana, no se trabajó") == {"trabajos": [], "dudas": [], "sugerencias": []}


def test_chat_responde_costos_con_los_numeros_del_panel():
    from nexo_ia import consultas, costos
    D.usar(REPO_ID)
    assert consultas.es_pregunta("¿Cuánto llevamos valorizado este mes?") and not consultas.es_pregunta("Vaciado de columnas del piso 2")
    r = consultas.responder("cuánto llevamos valorizado", "2027-06-30")
    acum = next(c["valor"] for c in r["cifras"] if c["etiqueta"] == "Acumulado")
    assert abs(acum - costos.ev(hasta="2027-06-30")) < 0.01
    r = consultas.responder("saldo de la partida 04.05.01", "2027-06-30")
    assert r["tema"] == "partida" and "04.05.01" in r["texto"]
    assert consultas.responder("como va el concreto armado?", "2027-06-30")["tema"] == "capitulo"


# ---------------------------------------------------------------- varios modelos y publicación
def _zip_de_prueba(mid, ver, malicioso=False):
    ruta = empaquetar_version.empaquetar(D.REPO, D.MODELO_REPO, mid, ver, "prueba", "", TMP / f"{mid}_{ver}.zip")
    if malicioso:
        with zipfile.ZipFile(ruta, "a") as z:
            z.writestr("../../fuera.txt", "x")
    return ruta.read_bytes()


def test_publicar_versiones_inmutables_y_seguras():
    r = servidor.publicar(_zip_de_prueba("OBRA-B", "V1"), "prueba")
    assert (D.MODELOS / "OBRA-B" / "V1" / "modelo.json").exists()
    try:
        servidor.publicar(_zip_de_prueba("OBRA-B", "V1"), "prueba"); assert False, "debió rechazar la versión repetida"
    except FileExistsError:
        pass
    try:
        servidor.publicar(_zip_de_prueba("OBRA-B", "V9", malicioso=True), "prueba"); assert False, "debió rechazar ../"
    except ValueError:
        pass
    assert not (D.MODELOS / "OBRA-B" / "V9").exists() and not (TMP / "fuera.txt").exists()
    servidor.publicar(_zip_de_prueba("OBRA-B", "V2"), "prueba")
    m = next(x for x in D.listar() if x["id"] == "OBRA-B")
    assert m["vigente"] == "V2" and [v["version"] for v in m["versiones"]] == ["V2", "V1"]
    assert r["id"] == "OBRA-B"


def test_estado_separado_por_modelo():
    if "OBRA-B" not in D.registro():
        servidor.publicar(_zip_de_prueba("OBRA-B", "V1"), "prueba")
    D.usar(REPO_ID)
    antes = D.ruta_registros().read_text()
    D.usar("OBRA-B")
    e = next(iter(D.elementos().values()))
    servidor.registrar({"fecha": "2027-06-11", "registros": [{"id": e["id"], "item": e["partidas"][0]["item"], "cantidad": 0.001}]})
    assert "2027-06-11" in D.ruta_registros().read_text()
    D.usar(REPO_ID)
    assert D.ruta_registros().read_text() == antes, "registrar en OBRA-B no debe tocar otro modelo"


if __name__ == "__main__":
    try:
        for n, f in list(globals().items()):
            if n.startswith("test_"):
                t = time.time(); f(); print(f"ok  {n}  ({time.time() - t:.1f}s)")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
