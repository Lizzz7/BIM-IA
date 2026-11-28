"""Adaptador acotado a Excel/modelos autorizados. Nunca acepta rutas del cliente."""
from copy import deepcopy
import hashlib
import re
from nexo.modulos.presupuestos.dominio.objetos_valor import numero


class CatalogoArchivos:
    def __init__(self, modelo, modelos):
        self.modelo = modelo
        self.modelos = modelos

    def _archivos(self):
        actual = self.modelo.F.get("presupuesto")
        archivos = {"actual": actual} if actual and actual.is_file() else {}
        if actual:
            # Solo revisiones hermanas del mismo presupuesto autorizado.
            raiz = re.sub(r"_v\d+$", "", actual.stem)
            for p in actual.parent.glob(raiz + "_v*.xlsx"):
                if re.fullmatch(re.escape(raiz) + r"_v\d+", p.stem):
                    archivos[p.stem[len(raiz)+1:]] = p
        return archivos

    def listar(self):
        return ([{"id": k, "nombre": p.name} for k, p in self._archivos().items()] +
                [{"id": "modelo:" + v, "nombre": "Modelo publicado " + v}
                 for v in sorted(self.modelos)])

    def leer(self, identificador):
        if not isinstance(identificador, str):
            raise ValueError("Versión de presupuesto no válida.")
        if identificador.startswith("modelo:"):
            modelo = self.modelos.get(identificador[7:])
            if not modelo:
                raise ValueError("Versión publicada inexistente.")
            return {"fuente": modelo.resumen(), "partidas": deepcopy(list(modelo.partidas.values())),
                    "apu": {}, "recursos": {}}
        ruta = self._archivos().get(identificador)
        if not ruta:
            raise ValueError("Versión de presupuesto no permitida.")
        from openpyxl import load_workbook
        wb = load_workbook(ruta, data_only=True, read_only=True)
        try:
            partidas, apu, recursos = [], {}, {}
            for fila, v in enumerate(wb["Presupuesto"].values, 1):
                if isinstance(v[0], str) and re.fullmatch(r"\d{2}(?:\.\d{2})+", v[0]) and v[2]:
                    partidas.append({"item": v[0], "desc": v[1], "und": v[2],
                                     "metrado": str(numero(v[3])), "pu": str(numero(v[4])),
                                     "fuente": f"{ruta.name}#Presupuesto!A{fila}:F{fila}"})
            if "Análisis de Precios Unitarios" in wb.sheetnames:
                actual = None
                for fila, v in enumerate(wb["Análisis de Precios Unitarios"].values, 1):
                    if v[0] == "Partida":
                        actual = str(v[1]).split()[0]
                        apu[actual] = []
                    elif actual and isinstance(v[0], str) and re.fullmatch(r"\d{10}", v[0]):
                        apu[actual].append({"codigo": v[0], "desc": v[1], "und": v[2],
                                            "cantidad": str(numero(v[4])), "precio": str(numero(v[5])),
                                            "fuente": f"{ruta.name}#APU!A{fila}:G{fila}"})
            if "Precios y Cantidades Recursos" in wb.sheetnames:
                for v in wb["Precios y Cantidades Recursos"].values:
                    if isinstance(v[0], str) and re.fullmatch(r"02\d{8}", v[0]):
                        recursos[v[0]] = {"codigo": v[0], "desc": v[1], "und": v[2],
                                          "precio": str(numero(v[4])), "fuente": str(v[6] or "Sin fuente")}
            if not partidas:
                raise ValueError("Presupuesto sin partidas calculables.")
            return {"fuente": {"archivo": ruta.name, "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest()},
                    "partidas": partidas, "apu": apu, "recursos": recursos}
        finally:
            wb.close()
