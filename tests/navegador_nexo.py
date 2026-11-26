"""Recorrido Chromium opcional: no escribe sobre datos ni presupuestos originales."""
from pathlib import Path
import sys
import tempfile
import threading

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "nexo-ia"))
from servidor import crear_servidor


def main():
    carpeta = Path("/tmp/opencode")
    with tempfile.TemporaryDirectory(dir=carpeta if carpeta.is_dir() else None) as tmp:
        servidor = crear_servidor(RAIZ, tmp, 0)
        hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
        hilo.start()
        try:
            with sync_playwright() as p:
                navegador = p.chromium.launch(headless=True, args=[
                    "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
                pagina = navegador.new_page(viewport={"width": 1440, "height": 1000})
                errores = []
                pagina.on("pageerror", lambda error: errores.append(str(error)))
                pagina.goto(f"http://127.0.0.1:{servidor.server_port}/")
                pagina.wait_for_function("S.geo !== null")
                assert "Sin Revit" in pagina.locator("#estado").inner_text()
                for nombre in ("inicio", "visor", "partidas", "parte", "cronograma",
                               "valorizaciones", "control", "config", "revision"):
                    pagina.locator(f'[data-pag="{nombre}"]').click()
                    assert pagina.locator(f"#pag-{nombre}").is_visible()
                pagina.locator("#iaCaso").select_option("controlado")
                pagina.locator("#iaAnalizar").click()
                pagina.wait_for_selector(".ia-finding")
                assert pagina.locator(".ia-finding").count() == 6
                pagina.locator("#iaExplicar").click()
                pagina.wait_for_selector("#iaExplanation .ia-banner")
                assert "no fue generada por IA" in pagina.locator("#iaExplanation").inner_text()
                pagina.locator("#iaMotivo").fill("Revisión controlada del caso simulado.")
                pagina.locator('[data-revision="Confirmado"]').click()
                pagina.wait_for_function("document.querySelector('.ia-finding[aria-pressed=true]').textContent.includes('Confirmado')")
                pagina.locator('[data-iatab="vinculacion"]').click()
                pagina.locator("#iaSugerir").click()
                pagina.wait_for_selector("#iaSuggestions table")
                assert pagina.locator("#iaSuggestions tbody tr").count() > 0
                pagina.locator('[data-iatab="versiones"]').click()
                pagina.locator("#iaComparar").click()
                pagina.wait_for_selector("#iaComparison table")
                assert "34,390.75" in pagina.locator("#iaComparison .ia-summary").inner_text()
                pagina.locator('[data-iatab="escenario"]').click()
                pagina.locator("#iaSolicitud").fill("El precio del acero sube 5 %")
                pagina.locator("#iaInterpretar").click()
                pagina.wait_for_selector("#iaProposal .ia-banner")
                pagina.locator("#iaSimular").click()
                pagina.locator("#dlgBotones button").filter(has_text="Simular").click()
                pagina.wait_for_selector("#iaScenario table")
                assert "20,746.68" in pagina.locator("#iaScenario .ia-summary").inner_text()
                assert not errores, errores
                navegador.close()
                print("OK: nueve secciones, auditoría, revisión, candidatas, comparación y escenario.")
        finally:
            servidor.shutdown()
            servidor.server_close()
            hilo.join()


if __name__ == "__main__":
    main()
