"""Reglas nuevas y compatibilidad. Datos temporales, sin migración de persistencia."""
import ast
from copy import deepcopy
from decimal import Decimal
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import nexo
from nexo.modulos.presupuestos.dominio.objetos_valor import Cotizacion, numero, moneda
from nexo.modulos.presupuestos.dominio.reglas import comparar, cotizar
from nexo.modulos.avances.aplicacion.registrar import ejecutar
from nexo.modulos.avances.infraestructura.repositorio_archivos import RegistrosJSON
from nexo.modulos.presupuestos.infraestructura.catalogo_archivos import CatalogoArchivos
from nexo.modulos.presupuestos.infraestructura.repositorio_archivos import RevisionesJSON
from nexo.modulos.presupuestos.aplicacion.casos_uso.comparar_versiones import ejecutar as comparar_versiones


def presupuesto(q="10", precio="20"):
    return {"fuente": {"archivo": "prueba"}, "partidas": [
        {"item": "01.01", "desc": "CONCRETO", "und": "m3", "metrado": q, "pu": precio}],
        "recursos": {"02": {"codigo": "02", "desc": "Cemento", "und": "bol"}},
        "apu": {"01.01": [{"codigo": "02", "desc": "Cemento", "und": "bol",
                          "cantidad": "2", "precio": "3", "fuente": "APU fila control"}]}}


class PresupuestoTests(unittest.TestCase):
    def test_descomposicion_y_redondeo(self):
        r = comparar(presupuesto("100", "300"), presupuesto("108", "330"))
        self.assertEqual(r["totales"]["cantidad"], 2400)
        self.assertEqual(r["totales"]["precio"], 3240)
        self.assertEqual(r["delta"], 5640)
        self.assertTrue(r["reconciliado"])
        for q in ("0.3333", "1.005", "10.3234"):
            self.assertTrue(comparar(presupuesto(q, "3.335"), presupuesto("2.1111", "4.675"))["reconciliado"])

    def test_unidad_diferente_no_finge_descomposicion(self):
        b = presupuesto()
        b["partidas"][0]["und"] = "kg"
        r = comparar(presupuesto(), b)
        self.assertEqual(r["filas"][0]["tipo"], "Unidad distinta")
        self.assertEqual(r["totales"]["precio"], 0)

    def test_cotizacion_documentada_y_sin_mutacion(self):
        a = presupuesto()
        original = deepcopy(a)
        c = Cotizacion("02", Decimal("4.72"), "bol", "Proveedor oferta A", "2026-11-28",
                       True, Decimal(".18"), alcance="Misma especificación, entrega en obra, sin flete adicional")
        r = cotizar(a, c)
        self.assertEqual(r["delta"], 20)
        self.assertEqual(r["cotizacion"]["precio_sin_igv"], "4.00")
        self.assertEqual(r["cambios_apu"][0]["pu_nuevo"], "22.00")
        self.assertEqual(a, original)
        self.assertTrue(r["no_modifica_original"])

    def test_cotizacion_rechaza_unidad_fuente_igv_y_moneda(self):
        args = dict(codigo="02", precio=Decimal(3), unidad="bol", fuente="Oferta", fecha="2026-11-28",
                    incluye_igv=False, tasa_igv=Decimal(".18"), alcance="Mismo alcance")
        for campo,valor in [("fuente",""),("moneda","USD"),("fecha","2026-02-30"),("incluye_igv","sí"),("alcance","")]:
            with self.assertRaises(ValueError):
                Cotizacion(**{**args,campo:valor})
        with self.assertRaises(ValueError):
            cotizar(presupuesto(), Cotizacion(**{**args,"unidad":"kg"}))
        for v in (True, "NaN", "Infinity", None):
            with self.assertRaises(ValueError):
                numero(v)
        self.assertEqual(moneda("-1.005"), Decimal("-1.01"))

    def test_atribucion_apu_y_ausencia_explicita(self):
        a,b=presupuesto(),presupuesto(precio="23")
        b["apu"]["01.01"][0]["precio"]="4"
        class Catalogo:
            def leer(self, clave): return {"a":a,"b":b}[clave]
        r=comparar_versiones(Catalogo(),"a","b")
        self.assertEqual(r["explicacion_apu"][0]["residuo_pu"],"1.00")
        b["apu"]={}
        self.assertIn("Sin APU",comparar_versiones(Catalogo(),"a","b")["explicacion_apu"][0]["estado"])

    def test_revision_inmutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=RevisionesJSON(tmp)
            p={"importe":123,"fuente":"Oferta control"}
            i=repo.guardar(p)
            antes=(Path(tmp)/(i+".json")).read_bytes()
            self.assertEqual(i,repo.guardar(p))
            self.assertEqual(antes,(Path(tmp)/(i+".json")).read_bytes())
            self.assertNotEqual(i,repo.guardar({**p,"importe":124}))

    def test_excel_actual_y_comparacion_real(self):
        from nexo_ia import datos as D
        m=D._modelo_del_repo()
        c=CatalogoArchivos(m,{m.version:m})
        r=comparar_versiones(c,"v3","actual")
        self.assertEqual(r["delta"],34390.75)
        self.assertTrue(r["reconciliado"])
        self.assertEqual(r["totales"]["nueva"],2445382.48)
        with self.assertRaises(ValueError):
            c.leer("../../.env")


class AvancesTests(unittest.TestCase):
    def test_idempotencia_atomica_y_rechazo_de_lotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta=Path(tmp)/"registros.json"
            ruta.write_text('{"elementos":{},"global":""}')
            repo=RegistrosJSON(ruta)
            partidas={"01":{"metrado":10,"pu":300,"und":"m3"}}
            elementos={1:{"tipo":"Columna","partidas":[{"item":"01","metrado":10}]}}
            p={"request_id":"abc","fecha":"2027-03-20","registros":[{"id":1,"item":"01","cantidad":2}]}
            ejecutar(repo,p,partidas,elementos,"v1")
            a=ruta.read_bytes()
            self.assertTrue(ejecutar(repo,p,partidas,elementos,"v1")["reintento"])
            self.assertEqual(a,ruta.read_bytes())
            with self.assertRaises(ValueError):
                ejecutar(repo,{**p,"fecha":"2027-03-21"},partidas,elementos,"v1")
            mezcla={**p,"request_id":"otro","registros":p["registros"]+[{"id":1,"item":"NO_EXISTE","cantidad":1}]}
            r=ejecutar(repo,mezcla,partidas,elementos,"v1")
            self.assertFalse(r["guardado"])
            self.assertFalse(r["aplicados"])
            self.assertEqual(a,ruta.read_bytes())
            ejecutar(repo,{**p,"request_id":"sim"},partidas,elementos,"v1",simular=True)
            self.assertEqual(a,ruta.read_bytes())

    def test_imports_compatibles_no_duplican_estado(self):
        from nexo_ia import datos, ifc_modelo, escaneo
        self.assertIs(datos,importlib.import_module("nexo.modulos.proyectos.infraestructura.repositorio_archivos"))
        self.assertIs(ifc_modelo,importlib.import_module("nexo.integraciones.ifc.modelo"))
        self.assertIs(escaneo,importlib.import_module("nexo.modulos.evidencia_bim.aplicacion.escaneo"))

    def test_dominio_no_importa_adaptadores(self):
        for p in (RAIZ/"nexo/modulos").glob("*/dominio/*.py"):
            for n in ast.walk(ast.parse(p.read_text())):
                if isinstance(n,ast.ImportFrom):
                    self.assertFalse(any(t in (n.module or "") for t in ("infraestructura","nexo_ia","openpyxl","ifcopenshell","http")),str(p))
                if isinstance(n,ast.Import):
                    self.assertFalse(any(a.name in ("sqlite3","requests","openpyxl","ifcopenshell") for a in n.names),str(p))


if __name__=="__main__":
    unittest.main()
