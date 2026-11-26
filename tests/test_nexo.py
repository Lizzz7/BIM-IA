"""Pruebas reproducibles: reglas, cálculos, persistencia, proveedor simulado y HTTP."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "nexo-ia"))

from servidor import Aplicacion, crear_servidor
from nexo_ia.demo import ESPERADOS, caso_controlado
from nexo_ia.motor import auditar, comparar, moneda, numero, unidad
from nexo_ia.proveedor import ProveedorIA
from nexo_ia.semantica import sugerir


def temporal():
    carpeta = Path("/tmp/opencode")
    return tempfile.TemporaryDirectory(dir=carpeta if carpeta.is_dir() else None)


def base_limpia():
    return {"partidas": [{"item": "01", "desc": "CONCRETO f'c=280 EN ZAPATAS", "und": "m3", "metrado": 10, "pu": 300}],
            "elementos": [{"id": 1, "tipo": "Zapata", "grupo": "ZAP",
                           "partidas": [{"item": "01", "clase": "concreto", "metrado": 10}]}]}


def registro(id="r1", cantidad="5", fecha="2027-03-20"):
    return {"id": id, "element_id": 1, "item": "01", "fecha": fecha, "cantidad": cantidad}


class ReglasTests(unittest.TestCase):
    def test_caso_valido_no_produce_alarmas(self):
        r = auditar(base_limpia(), [registro()], corte="2027-03-20")
        self.assertEqual(r["hallazgos"], [])

    def test_exceso_no_se_suma_dos_veces(self):
        r = auditar(base_limpia(), [registro(cantidad="12")], corte="2027-03-20")
        self.assertEqual({h["regla"] for h in r["hallazgos"]}, {"exceso_partida", "exceso_elemento"})
        self.assertEqual(r["resumen"]["importe_excesos_partida"], 600)
        self.assertEqual(sum(h["importe"] or 0 for h in r["hallazgos"]), 600)

    def test_coincidencias_son_solo_advertencias(self):
        r = auditar(base_limpia(), [registro("a", "2"), registro("b", "2")], corte="2027-03-20")
        self.assertEqual(r["hallazgos"][0]["regla"], "posible_duplicado")
        self.assertEqual(r["hallazgos"][0]["nivel"], "advertencia")
        self.assertIsNone(r["hallazgos"][0]["importe"])

    def test_fecha_de_corte_inclusiva(self):
        r = auditar(base_limpia(), [registro("a", "5"), registro("b", "9", "2027-03-21")], corte="2027-03-20")
        self.assertEqual(r["hallazgos"], [])
        self.assertEqual(r["cobertura"]["registros_posteriores_al_corte"], 1)

    def test_registro_invalido_no_desaparece_silenciosamente(self):
        r = auditar(base_limpia(), [registro(cantidad="NaN")], corte="2027-03-20")
        self.assertEqual(r["cobertura"]["registros_excluidos"], 1)
        self.assertEqual(r["hallazgos"][0]["regla"], "registro_invalido")

    def test_fecha_invalida_es_detectada(self):
        r = auditar(base_limpia(), [registro(fecha="2027-02-30")], corte="2027-03-20")
        self.assertEqual(r["hallazgos"][0]["regla"], "registro_invalido")

    def test_sin_material_no_inventa_resistencia(self):
        b = base_limpia()
        b["partidas"][0]["desc"] = "CONCRETO f'c=350"
        r = auditar(b, [], corte="2027-03-20")
        self.assertFalse(any(h["regla"] == "resistencia_distinta" for h in r["hallazgos"]))
        self.assertEqual(r["cobertura"]["vinculos_con_fc_comprobado"], 0)

    def test_fuentes_cambiadas_invalidan_identificador_de_revision(self):
        a = auditar(base_limpia(), [registro(cantidad="12")], corte="2027-03-20")
        b = auditar(base_limpia(), [registro(cantidad="13")], corte="2027-03-20")
        self.assertNotEqual(a["hallazgos"][0]["id"], b["hallazgos"][0]["id"])

    def test_moneda_y_numeros(self):
        self.assertEqual(moneda("1.005"), Decimal("1.01"))
        self.assertEqual(moneda("-1.005"), Decimal("-1.01"))
        self.assertEqual(unidad("m³"), "m3")
        for n in (True, None, "Infinity", "NaN"):
            with self.assertRaises(ValueError):
                numero(n)

    def test_diferencia_modelo_es_advertencia(self):
        b = base_limpia()
        b["elementos"][0]["partidas"][0]["metrado"] = 8
        h = auditar(b, [], corte="2027-03-20")["hallazgos"][0]
        self.assertEqual(h["regla"], "diferencia_modelo")
        self.assertEqual(h["nivel"], "advertencia")
        self.assertIsNone(h["importe"])


class ComparacionTests(unittest.TestCase):
    def version(self, q, pu, und="m3", archivo="test"):
        return {"fuente": {"archivo": archivo},
                "partidas": [{"item": "01", "desc": "Concreto", "und": und, "metrado": q, "pu": pu}]}

    def test_cantidad_precio_y_termino_cruzado(self):
        r = comparar(self.version(100, 300), self.version(108, 330))
        self.assertEqual(r["totales"]["cantidad"], 2400)
        self.assertEqual(r["totales"]["precio"], 3240)
        self.assertEqual(r["delta"], 5640)
        self.assertTrue(r["reconciliado"])

    def test_cambio_unidad_no_descompone_cantidad_precio(self):
        r = comparar(self.version(10, 3), self.version(15, 4, "m2"))
        self.assertEqual(r["totales"]["cantidad"], 0)
        self.assertEqual(r["totales"]["precio"], 0)
        self.assertEqual(r["totales"]["no_comparable"], 30)

    def test_altas_y_bajas(self):
        a, b = self.version(10, 3), self.version(5, 4)
        b["partidas"][0]["item"] = "02"
        r = comparar(a, b)
        self.assertEqual(r["totales"]["altas"], 20)
        self.assertEqual(r["totales"]["bajas"], -30)
        self.assertTrue(r["reconciliado"])

    def test_redondeo_reconcilia(self):
        for q1, q2 in [("0.3333", "0.6666"), ("1.005", "2.1111"), ("10.3234", "10.3555")]:
            r = comparar(self.version(q1, "3.335"), self.version(q2, "4.675"))
            self.assertTrue(r["reconciliado"])

    def test_solo_cambio_fuente_no_es_cambio_presupuestal(self):
        r = comparar(self.version(10, 3, archivo="a"), self.version(10, 3, archivo="b"))
        self.assertEqual(r["filas"][0]["tipo"], "Sin cambio")

    def test_no_acepta_codigos_repetidos(self):
        a = self.version(10, 3)
        a["partidas"].append(deepcopy(a["partidas"][0]))
        with self.assertRaises(ValueError):
            comparar(a, self.version(10, 3))


class ProveedorTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.p = ProveedorIA()

    def test_fallback_no_se_presenta_como_ia(self):
        r = self.p.explicar({"id": "abc", "detalle": "Detalle", "accion": "Revisar"})
        self.assertEqual(r["modo"], "sin_proveedor")

    def test_no_envia_red_por_defecto(self):
        with patch.object(self.p, "_post", side_effect=AssertionError("No llamar red")):
            self.p.explicar({"id": "abc", "detalle": "Detalle", "accion": "Revisar"})
            sugerir(base_limpia(), {}, 1, "concreto", self.p)

    def test_llm_acepta_cita_conocida(self):
        self.p.base, self.p.modelo = "https://ejemplo.invalid/v1", "modelo-prueba"
        with patch.object(self.p, "_post", return_value={"choices": [{"message": {"content": json.dumps(
                {"texto": "Revisar el alcance.", "accion": "Contrastar con el responsable.", "citas": ["abc"]})}}]}):
            self.assertEqual(self.p.explicar({"id": "abc"})["modo"], "llm")

    def test_llm_rechaza_cita_inventada_y_calculo_generado(self):
        self.p.base, self.p.modelo = "https://ejemplo.invalid/v1", "modelo-prueba"
        for salida in [{"texto": "Importe 999", "accion": "Revisar", "citas": ["abc"]},
                       {"texto": "Revisar", "accion": "Revisar", "citas": ["otra"]}]:
            with patch.object(self.p, "_post", return_value={"choices": [{"message": {"content": json.dumps(salida)}}]}):
                with self.assertRaises(ValueError):
                    self.p.explicar({"id": "abc"})

    def test_embeddings_restricciones_y_cache(self):
        self.p.base, self.p.embedding = "https://ejemplo.invalid/v1", "emb-prueba"
        b = base_limpia()
        b["partidas"] += [{"item": "02", "desc": "CONCRETO f'c=350", "und": "m3", "metrado": 1, "pu": 3},
                          {"item": "03", "desc": "CONCRETO f'c=280", "und": "kg", "metrado": 1, "pu": 3}]
        def respuesta(ruta, datos):
            return {"data": [{"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(datos["input"])]}
        with patch.object(self.p, "_post", side_effect=respuesta) as mock:
            for _ in range(2):
                r = sugerir(b, {1: {"materiales": [{"material": "Concreto f'c=280"}]}},
                            1, "concreto", self.p, usar_ia=True)
            self.assertEqual(mock.call_count, 1)
            self.assertEqual([c["item"] for c in r["candidatas"]], ["01"])

    def test_interpretacion_local_pide_direccion_y_catalogo(self):
        recursos = {"ac": {"desc": "ACERO CORRUGADO"}, "ce": {"desc": "CEMENTO PORTLAND"}}
        r = self.p.interpretar_escenario("El precio del acero baja 5 %", recursos)
        self.assertEqual((r["codigo"], r["porcentaje"]), ("ac", "-5"))
        with self.assertRaises(ValueError):
            self.p.interpretar_escenario("Acero 5 %", recursos)
        with self.assertRaises(ValueError):
            self.p.interpretar_escenario("El precio de algo sube 5 %", recursos)


class AplicacionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = temporal()
        cls.app = Aplicacion(RAIZ, cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_datos_y_geometria_sin_revit(self):
        self.assertEqual(len(self.app.exportacion.base["partidas"]), 61)
        self.assertEqual(len(self.app.exportacion.geometria()["elementos"]), 1266)
        self.assertIn("Revisión IA", self.app.exportacion.html())

    def test_caso_controlado_reproducible_y_aislado(self):
        antes = self.app.almacen.registros()
        r = self.app.auditoria("controlado")
        self.assertEqual({h["regla"] for h in r["hallazgos"]}, ESPERADOS)
        self.assertTrue(r["validacion_controlada"]["coinciden"])
        self.assertEqual(r["resumen"]["importe_excesos_partida"], 600)
        self.assertEqual(antes, self.app.almacen.registros())

    def test_presupuesto_actual_contraste_y_versiones(self):
        p = self.app.versiones.leer("v4")
        total = sum(moneda(numero(x["metrado"])*numero(x["pu"])) for x in p["partidas"])
        self.assertEqual(total, Decimal("2445382.48"))
        r = self.app.versiones.comparar("v3", "v4")
        self.assertTrue(r["reconciliado"])
        self.assertEqual(r["delta"], 34390.75)

    def test_escenario_cero_identico_y_no_modifica_base(self):
        antes = self.app.versiones.leer("v4")
        self.assertEqual(self.app.versiones.escenario("v4", "0203020003", 0)["delta"], 0)
        r = self.app.versiones.escenario("v4", "0203020003", 5)
        self.assertTrue(r["reconciliado"])
        self.assertGreater(r["delta"], 0)
        self.assertEqual(antes, self.app.versiones.leer("v4"))
        self.assertTrue(all(f["cantidad"] == 0 for f in r["filas"]))

    def test_registro_atomico_idempotente_y_simulacion(self):
        with temporal() as tmp:
            a = Aplicacion(RAIZ, tmp)
            e = a.exportacion.base["elementos"][0]
            p = {"fecha": "2027-03-20", "request_id": "prueba",
                 "registros": [{"id": e["id"], "item": e["partidas"][0]["item"], "cantidad": 0.001}]}
            n = len(a.almacen.registros())
            self.assertTrue(a.registrar({**p, "simular": True})["simulado"])
            self.assertEqual(len(a.almacen.registros()), n)
            a.registrar(p)
            a.registrar(p)
            self.assertEqual(len(a.almacen.registros()), n+1)
            with self.assertRaises(ValueError):
                a.registrar({**p, "fecha": "2027-03-21"})
            with self.assertRaises(ValueError):
                a.registrar({**p, "request_id": "error", "registros": p["registros"] + [
                    {"id": 0, "item": "INEXISTENTE", "cantidad": 1}]})
            self.assertEqual(len(a.almacen.registros()), n+1)

    def test_revisiones_con_motivo_y_persistencia(self):
        h = self.app.auditoria("controlado")["hallazgos"][0]
        with self.assertRaises(ValueError):
            self.app.almacen.revisar(h["id"], "Confirmado", "")
        self.app.almacen.revisar(h["id"], "Descartado", "Contraste académico de prueba.")
        r = self.app.auditoria("controlado")
        self.assertEqual(next(x for x in r["hallazgos"] if x["id"] == h["id"])["revision"]["estado"], "Descartado")


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = temporal()
        cls.server = crear_servidor(RAIZ, cls.tmp.name, 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.tmp.cleanup()

    def test_html_y_api(self):
        with urlopen(self.url) as r:
            self.assertIn("Revisar antes de aprobar", r.read().decode())
        with urlopen(self.url + "/api/auditoria?caso=controlado") as r:
            self.assertTrue(json.load(r)["validacion_controlada"]["coinciden"])

    def test_origen_y_host_externos_rechazados(self):
        for cab in [{"Origin": "https://sitio-externo.invalid"}, {"Host": "rebind.invalid"}]:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(self.url + "/api/datos", headers=cab))
            self.assertEqual(error.exception.code, 403)

    def test_no_expone_archivos_o_rutas_arbitrarias(self):
        for ruta in ("/.env", "/api/comparacion?a=../../.env"):
            with self.assertRaises(HTTPError):
                urlopen(self.url + ruta)

    def test_metrado_sin_idempotencia_y_json_invalido(self):
        for body in (b"{}", b'{"fecha":NaN}'):
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(self.url + "/api/metrado", data=body, headers={"Content-Type": "application/json"}))
            self.assertEqual(error.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
