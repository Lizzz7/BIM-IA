"""Comparación portada de Liz: todos los componentes reconcilian al céntimo."""
from copy import deepcopy
from decimal import Decimal
from .objetos_valor import moneda, numero, unidad


def comparar(a, b):
    def indice(version):
        out = {}
        for p in version["partidas"]:
            if p["item"] in out:
                raise ValueError("Partida repetida: " + p["item"])
            if numero(p["metrado"]) < 0 or numero(p["pu"]) < 0:
                raise ValueError("Cantidad o precio negativo.")
            out[p["item"]] = p
        return out
    aa, bb = indice(a), indice(b)
    componentes = ("cantidad", "precio", "altas", "bajas", "no_comparable", "redondeo")
    totales = dict.fromkeys(("base", "nueva") + componentes, Decimal(0))
    filas = []
    for it in sorted(aa.keys() | bb.keys()):
        p, q = aa.get(it), bb.get(it)
        v1 = moneda(numero(p["metrado"]) * numero(p["pu"])) if p else Decimal(0)
        v2 = moneda(numero(q["metrado"]) * numero(q["pu"])) if q else Decimal(0)
        efectos = dict.fromkeys(componentes, Decimal(0))
        if not p:
            tipo, efectos["altas"] = "Nueva", v2
        elif not q:
            tipo, efectos["bajas"] = "Retirada", -v1
        elif unidad(p["und"]) != unidad(q["und"]):
            tipo, efectos["no_comparable"] = "Unidad distinta", v2 - v1
        else:
            cambio = any(p.get(k) != q.get(k) for k in ("desc", "und")) or any(
                numero(p[k]) != numero(q[k]) for k in ("metrado", "pu"))
            tipo = "Modificada" if cambio else "Sin cambio"
            efectos["cantidad"] = moneda((numero(q["metrado"]) - numero(p["metrado"])) * numero(p["pu"]))
            efectos["precio"] = moneda(numero(q["metrado"]) * (numero(q["pu"]) - numero(p["pu"])))
            efectos["redondeo"] = v2 - v1 - efectos["cantidad"] - efectos["precio"]
        totales["base"] += v1
        totales["nueva"] += v2
        for k, v in efectos.items():
            totales[k] += v
        filas.append({"item": it, "desc": (q or p)["desc"], "tipo": tipo, "a": p, "b": q,
                      "base": float(v1), "nueva": float(v2), "delta": float(v2-v1),
                      **{k: float(v) for k, v in efectos.items()}})
    delta = totales["nueva"] - totales["base"]
    return {"ok": True, "a": a["fuente"], "b": b["fuente"], "delta": float(delta),
            "totales": {k: float(v) for k, v in totales.items()},
            "reconciliado": delta == sum(totales[k] for k in componentes), "filas": filas,
            "metodo": "ΔQ × PU anterior + Q nueva × ΔPU; altas, bajas, unidades distintas y redondeo separados.",
            "limite": "Correspondencia por código; códigos renombrados aparecen como baja/alta. "
                      "No se infieren causas contractuales ni se modifica el presupuesto vigente."}


def cotizar(base, cotizacion):
    recursos = base.get("recursos", {})
    if cotizacion.codigo not in recursos:
        raise ValueError("El recurso no pertenece al catálogo de este presupuesto.")
    recurso = recursos[cotizacion.codigo]
    if unidad(cotizacion.unidad) != unidad(recurso["und"]):
        raise ValueError("Unidad incompatible. No se convierte automáticamente.")
    nueva, cambios = deepcopy(base), []
    for p in nueva["partidas"]:
        lineas = [r for r in base.get("apu", {}).get(p["item"], []) if r["codigo"] == cotizacion.codigo]
        if not lineas:
            continue
        delta = Decimal(0)
        evidencia = []
        for r in lineas:
            if unidad(r["und"]) != unidad(cotizacion.unidad):
                raise ValueError("La unidad del recurso en el APU no es comparable.")
            anterior = moneda(numero(r["cantidad"]) * numero(r["precio"]))
            actualizado = moneda(numero(r["cantidad"]) * cotizacion.precio_sin_igv)
            delta += actualizado - anterior
            evidencia.append({**r, "precio_nuevo_sin_igv": str(cotizacion.precio_sin_igv),
                              "parcial_anterior": str(anterior), "parcial_nuevo": str(actualizado)})
        pu_anterior = numero(p["pu"])
        p["pu"] = str(moneda(pu_anterior + delta))
        cambios.append({"item": p["item"], "pu_base": str(pu_anterior), "pu_nuevo": p["pu"],
                        "recurso": cotizacion.codigo, "lineas": evidencia})
    if not cambios:
        raise ValueError("El recurso no tiene consumo identificable en los APU.")
    nueva["fuente"] = {"archivo": "Propuesta de cotización, no contractual",
                       "base": base["fuente"], "cotizacion": cotizacion.fuente}
    resultado = comparar(base, nueva)
    resultado.update({"recurso": recurso, "cambios_apu": cambios,
                      "cotizacion": {"codigo": cotizacion.codigo, "precio": str(cotizacion.precio),
                                    "precio_sin_igv": str(cotizacion.precio_sin_igv),
                                    "unidad": cotizacion.unidad, "fuente": cotizacion.fuente,
                                    "fecha": cotizacion.fecha, "incluye_igv": cotizacion.incluye_igv,
                                    "tasa_igv": str(cotizacion.tasa_igv), "moneda": cotizacion.moneda,
                                    "alcance": cotizacion.alcance},
                      "supuesto": "Se sustituye solo el parcial del recurso cotizado; cantidades, rendimientos, "
                                  "otros recursos e indirectos no cambian. Resultado de costo directo. "
                                  "El usuario declara comparabilidad del alcance, entrega y transporte.",
                      "no_modifica_original": True})
    return resultado
