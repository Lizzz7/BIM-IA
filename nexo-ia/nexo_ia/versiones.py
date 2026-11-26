"""Lectura acotada a los presupuestos autorizados del repositorio, no importador genérico."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import hashlib
import re

from .motor import comparar, moneda, numero


class Versiones:
    def __init__(self, raiz, modelo):
        carpeta = Path(raiz) / "5_Documentacion"
        self.archivos = {"original": carpeta / f"Presupuesto_Estructuras_{modelo}.xlsx"}
        self.archivos.update({f"v{i}": carpeta / f"Presupuesto_Estructuras_{modelo}_v{i}.xlsx" for i in (2, 3, 4)})
        self.archivos = {k: p for k, p in self.archivos.items() if p.is_file()}
        self.cache = {}

    def listar(self):
        return [{"id": k, "nombre": p.name} for k, p in self.archivos.items()]

    def leer(self, version):
        if version not in self.archivos:
            raise ValueError("Versión de presupuesto no permitida.")
        ruta = self.archivos[version]
        sello = ruta.stat().st_mtime_ns
        if (version, sello) in self.cache:
            return deepcopy(self.cache[(version, sello)])
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ValueError("Instala las dependencias: python -m pip install -r requirements.txt") from None
        wb = load_workbook(ruta, data_only=True, read_only=True)
        try:
            partidas, apu, recursos = [], {}, {}
            for fila, valores in enumerate(wb["Presupuesto"].values, 1):
                it, desc, und, met, pu = list(valores[:5])
                if isinstance(it, str) and re.fullmatch(r"\d{2}(?:\.\d{2})+", it) and und:
                    # Una fórmula sin resultado cacheado no es cero.
                    cantidad, precio = numero(met), numero(pu)
                    if cantidad < 0 or precio < 0:
                        raise ValueError(f"Cantidad o precio negativo en {ruta.name}, fila {fila}.")
                    partidas.append({"item": it, "desc": str(desc), "und": str(und),
                                     "metrado": str(cantidad), "pu": str(precio),
                                     "fuente": f"{ruta.name}#Presupuesto!A{fila}:F{fila}"})
            if not partidas:
                raise ValueError("El presupuesto no contiene partidas calculables.")
            if "Análisis de Precios Unitarios" in wb.sheetnames:
                actual = None
                for fila, v in enumerate(wb["Análisis de Precios Unitarios"].values, 1):
                    codigo = v[0]
                    if codigo == "Partida":
                        actual = str(v[1]).split()[0]
                        apu[actual] = []
                    elif actual and isinstance(codigo, str) and re.fullmatch(r"\d{10}", codigo):
                        apu[actual].append({"codigo": codigo, "desc": str(v[1]), "und": str(v[2]),
                                            "cantidad": str(numero(v[4])), "precio": str(numero(v[5])),
                                            "fuente": f"{ruta.name}#APU!A{fila}:G{fila}"})
            if "Precios y Cantidades Recursos" in wb.sheetnames:
                for v in wb["Precios y Cantidades Recursos"].values:
                    if isinstance(v[0], str) and re.fullmatch(r"\d{10}", v[0]) and v[0].startswith("02"):
                        recursos[v[0]] = {"codigo": v[0], "desc": str(v[1]), "und": str(v[2]),
                                          "precio": str(numero(v[4])), "fuente": str(v[6] or "No declarada")}
            resultado = {"fuente": {"id": version, "archivo": ruta.name,
                                   "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest()},
                         "partidas": partidas, "apu": apu, "recursos": recursos}
        finally:
            wb.close()
        self.cache[(version, sello)] = resultado
        return deepcopy(resultado)

    def comparar(self, a, b):
        return comparar(self.leer(a), self.leer(b))

    def escenario(self, version, codigo, porcentaje):
        base = self.leer(version)
        pct = numero(porcentaje)
        if not Decimal("-100") <= pct <= Decimal("100"):
            raise ValueError("El escenario admite variaciones de -100 % a 100 %.")
        if codigo not in base["recursos"]:
            raise ValueError("Elige un material del catálogo APU de esta versión.")
        nueva = deepcopy(base)
        cambios = []
        for p in nueva["partidas"]:
            lineas = base["apu"].get(p["item"], [])
            afectadas = [r for r in lineas if r["codigo"] == codigo]
            if not afectadas:
                continue
            delta_pu = Decimal(0)
            for r in afectadas:
                viejo = numero(r["precio"])
                nuevo = moneda(viejo * (1 + pct / 100))
                # Sustituir el parcial del recurso, conservando el PU base y los demás componentes.
                delta_pu += moneda(numero(r["cantidad"]) * nuevo) - moneda(numero(r["cantidad"]) * viejo)
            anterior = numero(p["pu"])
            p["pu"] = str(moneda(anterior + delta_pu))
            cambios.append({"item": p["item"], "pu_base": str(anterior), "pu_escenario": p["pu"],
                            "lineas": afectadas})
        nueva["fuente"] = {"id": "escenario", "archivo": "Escenario NO contractual",
                           "base_sha256": base["fuente"]["sha256"]}
        resultado = comparar(base, nueva)
        resultado.update({"recurso": base["recursos"][codigo], "porcentaje": str(pct),
                          "cambios_apu": cambios,
                          "supuesto": "Solo cambia el precio del material seleccionado en las líneas APU. "
                                      "Precios y parciales redondeados a dos decimales. Se mantienen cantidades, "
                                      "rendimientos, otros recursos e indirectos; resultado en costo directo.",
                          "no_modifica_original": True})
        return resultado
