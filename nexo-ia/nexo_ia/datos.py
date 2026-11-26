"""Adaptador de las exportaciones existentes. Nunca escribe sobre los originales."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json

from .motor import fecha_iso, numero


def json_archivo(ruta):
    return json.loads(Path(ruta).read_text(encoding="utf-8-sig"))


def incrustado(ruta, marca):
    texto = Path(ruta).read_text(encoding="utf-8")
    if marca not in texto:
        raise ValueError("No se encontró la exportación incrustada: " + marca)
    return json.JSONDecoder().raw_decode(texto.split(marca, 1)[1].lstrip())[0]


class Exportaciones:
    def __init__(self, raiz):
        self.raiz = Path(raiz)
        cron = json_archivo(self.raiz / "1_Panel/datos/nexo_no_datos.json")
        modelo = cron["proyecto"]["modelo"]
        ruta = self.raiz / "3_Modelo_y_parametros" / f"parametros_revit_{modelo}.json"
        pr = json_archivo(ruta)
        self.modelo = modelo
        self.proyecto_id = hashlib.sha256(modelo.encode()).hexdigest()[:16]
        self.crono = incrustado(self.raiz / "1_Panel/index.html", "const CRONO = ")
        if self.crono["modelo"] != modelo:
            raise ValueError("Cronograma incrustado y exportación pertenecen a modelos distintos.")
        self.base = {"ok": True, "modelo": modelo, "inicio": pr["inicio_obra"],
                     "pie": pr["pie"], "niveles": pr["niveles"], "capitulos": pr["capitulos"],
                     "partidas": pr["partidas"], "elementos": [
                         {**e, "existe": True, "registro": "", "obs": ""} for e in pr["elementos"]],
                     "registroGlobal": "", "parametrosFaltan": [], "modo": "exportado",
                     "proyecto_id": self.proyecto_id,
                     "presupuesto_version": hashlib.sha256(ruta.read_bytes()).hexdigest(),
                     "fuentes": {"presupuesto": ruta.name, "registros": f"registros_{modelo}.json",
                                 "geometria": "Instantánea exportada, no conexión en vivo"},
                     "advertencia": "Caso académico: avances de prueba y precios/criterios con supuestos. "
                                    "No representa costos reales ni aprobación contractual."}
        raw = json_archivo(self.raiz / "3_Modelo_y_parametros" / f"metrados_{modelo}.json")
        self.crudos = {e["id"]: e for e in raw["elementos"]}
        reg = json_archivo(self.raiz / "3_Modelo_y_parametros" / f"registros_{modelo}.json")
        self.iniciales = []
        for eid, cadena in [(0, reg.get("global", ""))] + [
                (int(eid), e.get("registro", "")) for eid, e in reg["elementos"].items()]:
            for i, linea in enumerate(cadena.split(";")):
                if not linea:
                    continue
                campos = linea.split("|")
                if len(campos) != 3:
                    raise ValueError(f"Registro de origen ilegible: elemento {eid}, línea {i + 1}")
                f, it, q = campos
                self.iniciales.append({"id": f"origen:{eid}:{i}", "element_id": eid, "item": it,
                                       "fecha": f, "cantidad": q, "fuente": f"{self.base['fuentes']['registros']}#{eid}/{i+1}"})
        self._geo = None

    def panel(self, registros):
        datos = deepcopy(self.base)
        elems = {e["id"]: e for e in datos["elementos"]}
        for r in registros:
            # La auditoría ve los registros inválidos, pero la UI de avance no los calcula.
            try:
                fecha_iso(r["fecha"])
                numero(r["cantidad"])
            except ValueError:
                continue
            if r["item"] not in {p["item"] for p in datos["partidas"]}:
                continue
            cadena = f'{r["fecha"]}|{r["item"]}|{r["cantidad"]};'
            if r["element_id"] in elems:
                elems[r["element_id"]]["registro"] += cadena
            elif r["element_id"] == 0:
                datos["registroGlobal"] += cadena
        return datos

    def geometria(self):
        if self._geo is None:
            snap = incrustado(self.raiz / "5_Documentacion/Compartir/NEXO_OBRA_solo_lectura.html",
                              "window.NEXO_SNAPSHOT=")
            if snap["datos"]["modelo"] != self.modelo:
                raise ValueError("La geometría exportada pertenece a otro modelo.")
            ids = {e["id"] for e in self.base["elementos"]}
            self._geo = {"elementos": [e for e in snap["geo"]["elementos"] if e["id"] in ids],
                         "fuente": "Instantánea de solo lectura", "fecha_exportacion": snap["fecha"]}
        return self._geo

    def html(self):
        panel = self.raiz / "1_Panel"
        html = (panel / "panel_fuente.html").read_text(encoding="utf-8")
        html = html.replace("/*__CRONOGRAMA__*/null", json.dumps(self.crono, ensure_ascii=False).replace("<", "\\u003c"))
        lib = (panel / "lib/exceljs.min.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
        html = html.replace("<!--__EXCELJS__-->", "<script>" + lib + "</script>")
        html = html.replace("/*__EXCEL__*/", (panel / "excel_valorizacion.js").read_text(encoding="utf-8"))
        css = (panel / "revision_ia.css").read_text(encoding="utf-8")
        js = (panel / "revision_ia.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
        return html.replace("<!--__REVISION_CSS__-->", "<style>" + css + "</style>").replace(
            "<!--__REVISION_JS__-->", "<script>" + js + "</script>")
