"""Recorrido Chromium con estado temporal. Instalar playwright y su Chromium para ejecutarlo."""
import os
from pathlib import Path
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

RAIZ=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(RAIZ))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["NEXO_ESTADO"]=tmp+"/estado"
        os.environ["NEXO_MODELOS"]=tmp+"/modelos"
        from nexo.api.http import Manejador
        servidor=ThreadingHTTPServer(("127.0.0.1",0),Manejador)
        servidor.daemon_threads=True
        hilo=threading.Thread(target=servidor.serve_forever,daemon=True)
        hilo.start()
        try:
            with sync_playwright() as p:
                b=p.chromium.launch(headless=True,args=["--use-gl=angle","--use-angle=swiftshader","--enable-unsafe-swiftshader"])
                page=b.new_page(viewport={"width":1440,"height":1000})
                errores=[]
                page.on("pageerror",lambda err:errores.append(str(err)))
                page.goto(f"http://127.0.0.1:{servidor.server_port}/")
                page.wait_for_function("S.geo !== null",timeout=60000)
                for seccion in ("inicio","visor","partidas","parte","cronograma","control","config","valorizaciones"):
                    page.locator(f'[data-pag="{seccion}"]').click()
                    assert page.locator(f"#pag-{seccion}").is_visible()
                page.wait_for_selector("#apuRevision")
                page.locator("#apuRevision details").first.locator("summary").click()
                page.wait_for_function("document.querySelector('#apuRecurso').options.length > 0")
                page.locator("#apuRecurso").select_option("0203020003")
                page.locator("#apuPrecio").fill("4.00")
                page.locator("#apuFuente").fill("Oferta de prueba independiente")
                page.locator("#apuAlcance").fill("Acero del mismo grado, entrega en obra y flete incluido.")
                page.locator("#apuProponer").click()
                page.wait_for_selector("#apuPropuesta [data-export]")
                assert "Comparación reconciliada" in page.locator("#apuPropuesta").inner_text()
                page.once("dialog",lambda dialog:dialog.accept())
                page.locator("#apuConfirmar").click()
                page.wait_for_function("document.querySelector('#apuMensaje').textContent.includes('ID:')")
                page.locator("#apuRevision > details").nth(1).locator("summary").click()
                page.locator("#apuComparar").click()
                page.wait_for_selector("#apuComparacion [data-export]")
                assert "34,390.75" in page.locator("#apuComparacion").inner_text()
                # Comprobar que los PU congelados no siguen los valores vivos.
                congelado=page.evaluate("""() => {
                  const v={act:{'01.01':10},ded:{},presupuesto:JSON.parse(JSON.stringify(presupuestoVz(null)))};
                  const antes=totalVz(v).cd, p=S.porItem['01.01'], pu=p.pu;
                  p.pu=9999;const despues=totalVz(v).cd;p.pu=pu;
                  return antes===despues;
                }""")
                assert congelado
                # La sección dron conserva carga IFC, simulación y acceso al historial.
                page.locator('[data-pag="parte"]').click()
                page.wait_for_selector("#iaDron",timeout=60000)
                assert page.locator("#iaDron").is_visible()
                assert not errores,errores
                b.close()
                print("OK Chromium: ocho secciones, cotización documentada, revisión, comparación, PU congelados y módulo dron.")
        finally:
            servidor.shutdown();servidor.server_close();hilo.join()


if __name__=="__main__":
    main()
