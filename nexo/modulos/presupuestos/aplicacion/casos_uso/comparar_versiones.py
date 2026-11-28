from nexo.modulos.presupuestos.dominio.reglas import comparar
from nexo.modulos.presupuestos.aplicacion.puertos import CatalogoPresupuestos


def ejecutar(catalogo: CatalogoPresupuestos, anterior, nueva):
    from decimal import Decimal
    from nexo.modulos.presupuestos.dominio.objetos_valor import moneda, numero
    a, b = catalogo.leer(anterior), catalogo.leer(nueva)
    resultado = comparar(a, b)
    explicacion = []
    for fila in resultado["filas"]:
        it = fila["item"]
        if not fila["a"] or not fila["b"] or fila["tipo"] == "Sin cambio":
            continue
        la, lb = a.get("apu", {}).get(it), b.get("apu", {}).get(it)
        if not la or not lb:
            explicacion.append({"item": it, "estado": "Sin APU comparables; no se atribuye el cambio a un recurso."})
            continue
        def por_codigo(lineas):
            out = {}
            for r in lineas:
                out.setdefault(r["codigo"], []).append(r)
            return out
        aa, bb = por_codigo(la), por_codigo(lb)
        cambios, total = [], Decimal(0)
        for codigo in sorted(aa.keys() | bb.keys()):
            antes = sum((moneda(numero(r["cantidad"]) * numero(r["precio"])) for r in aa.get(codigo, [])), Decimal(0))
            despues = sum((moneda(numero(r["cantidad"]) * numero(r["precio"])) for r in bb.get(codigo, [])), Decimal(0))
            delta = despues - antes
            total += delta
            if delta:
                cambios.append({"codigo": codigo, "delta_parcial_apu": str(delta),
                                "antes": aa.get(codigo, []), "despues": bb.get(codigo, [])})
        diferencia = numero(fila["b"]["pu"]) - numero(fila["a"]["pu"])
        explicacion.append({"item": it, "estado": "Diferencias documentadas de parciales APU, no causa contractual.",
                            "recursos": cambios, "delta_pu": str(diferencia),
                            "residuo_pu": str(moneda(diferencia-total)),
                            "nota": "El residuo conserva redondeos y componentes no explicados; no se inventan causas."})
    resultado["explicacion_apu"] = explicacion
    return resultado
