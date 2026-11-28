"""Contrato de las rutas nuevas: fuentes autorizadas, solo lectura y cotizaciones."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import nexo
from nexo.api import http
from nexo_ia import datos as D


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.estado=patch.object(D,"ESTADO",Path(cls.tmp.name)/"estado")
        cls.estado.start()
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),http.Manejador)
        cls.server.daemon_threads=True
        cls.hilo=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.hilo.start()
        cls.url=f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.hilo.join()
        cls.estado.stop();cls.tmp.cleanup()

    def pide(self,ruta,cuerpo=None,cab=None):
        req=Request(self.url+ruta,data=None if cuerpo is None else json.dumps(cuerpo).encode(),
                    headers={"Content-Type":"application/json",**(cab or {})})
        with urlopen(req,timeout=30) as r:
            return json.load(r)

    def cotizacion(self):
        return {"version":"actual","codigo":"0203020003","precio":"4","unidad":"kg",
                "fuente":"Oferta de prueba HTTP","fecha":"2026-11-28","incluye_igv":False,
                "tasa_igv":"0.18","alcance":"Mismo acero, entrega en obra y transporte incluido."}

    def test_comparacion_y_cotizacion_por_http(self):
        r=self.pide("/api/presupuestos/comparar?a=v3&b=actual")
        self.assertTrue(r["reconciliado"]);self.assertEqual(r["delta"],34390.75)
        r=self.pide("/api/presupuestos/cotizar",self.cotizacion())
        self.assertTrue(r["no_modifica_original"]);self.assertTrue(r["cambios_apu"])
        with patch.object(http,"SOLO_LECTURA",False),patch.object(http,"TOKEN",""):
            guardado=self.pide("/api/presupuestos/cotizar/confirmar",self.cotizacion())
        self.assertEqual(guardado["estado"],"Propuesta, no aprobada")

    def test_solo_lectura_no_confirma(self):
        with patch.object(http,"SOLO_LECTURA",True):
            self.assertTrue(self.pide("/api/presupuestos/cotizar",self.cotizacion())["ok"])
            with self.assertRaises(HTTPError) as err:
                self.pide("/api/presupuestos/cotizar/confirmar",self.cotizacion())
            self.assertEqual(err.exception.code,403)

    def test_rechaza_ruta_arbitraria_origen_y_cuerpo_invalido(self):
        for ruta,cuerpo,cab,codigo in [
            ("/api/presupuestos/comparar?a=../../.env&b=actual",None,None,400),
            ("/api/presupuestos/cotizar",[],None,400),
            ("/api/presupuestos/cotizar",{},{"Origin":"https://externo.invalid"},403)]:
            with self.assertRaises(HTTPError) as err:
                self.pide(ruta,cuerpo,cab)
            self.assertEqual(err.exception.code,codigo)


if __name__=="__main__":
    unittest.main()
