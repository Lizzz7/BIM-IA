"""Reglas reproducibles. No se confunden advertencias con errores o ahorros."""
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
import unicodedata


def numero(valor):
    if isinstance(valor, bool):
        raise ValueError("Un booleano no es una cantidad.")
    try:
        n = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        raise ValueError("Cantidad o precio no numérico.") from None
    if not n.is_finite() or abs(n) > Decimal("1e15"):
        raise ValueError("Cantidad o precio fuera de rango.")
    return n


def moneda(valor):
    return numero(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def texto(valor):
    return "".join(c for c in unicodedata.normalize("NFKD", str(valor or "").lower())
                   if not unicodedata.combining(c))


def unidad(valor):
    u = texto(valor).replace("³", "3").replace("²", "2").replace(" ", "").replace("^", "")
    return {"m³": "m3", "m²": "m2", "m3": "m3", "m2": "m2", "kgs": "kg",
            "unidad": "und", "unidades": "und", "u": "und", "un": "und"}.get(u, u)


def resistencia(valor):
    m = re.search(r"f\s*['’]?\s*c\s*=?\s*(\d{3})", texto(valor))
    return int(m[1]) if m else None


def fecha_iso(valor):
    if not isinstance(valor, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        raise ValueError("Fecha no válida (AAAA-MM-DD).")
    date.fromisoformat(valor)
    return valor


UNIDADES_CLASE = {"concreto": "m3", "encofrado": "m2", "acero": "kg", "ladrillo": "und"}


def auditar(base, registros, crudos=None, corte=None, tolerancia="0.03"):
    corte = fecha_iso(corte or date.today().isoformat())
    tol = numero(tolerancia)
    if not 0 <= tol <= 1:
        raise ValueError("La tolerancia debe estar entre 0 y 1.")
    partidas = {p["item"]: p for p in base["partidas"]}
    elementos = {e["id"]: e for e in base["elementos"]}
    crudos = crudos or {}
    hallazgos = []

    def agregar(regla, nivel, titulo, detalle, item=None, ids=(), evidencia=None,
                importe=None, accion="Revisar la fuente antes de modificar el presupuesto."):
        ev = evidencia or {}
        clave = json.dumps([regla, item, sorted(set(ids)), ev], sort_keys=True, ensure_ascii=False)
        hallazgos.append({
            "id": hashlib.sha256(clave.encode()).hexdigest()[:20], "regla": regla,
            "nivel": nivel, "titulo": titulo, "detalle": detalle, "item": item,
            "element_ids": sorted(set(ids)), "evidencia": ev,
            "importe": float(moneda(importe)) if importe is not None else None,
            "accion": accion, "motor": "Reglas verificables",
        })

    validos, excluidos, futuros = [], 0, 0
    for r in registros:
        ev = {"registro": r["id"], "fuente": r.get("fuente", "registro local"),
              "fecha": r.get("fecha"), "cantidad": r.get("cantidad")}
        try:
            fecha_iso(r.get("fecha"))
            q = numero(r.get("cantidad"))
        except ValueError as error:
            excluidos += 1
            agregar("registro_invalido", "inconsistencia", "Registro no calculable",
                    str(error), r.get("item"), evidencia=ev)
            continue
        if r["fecha"] > corte:
            futuros += 1
            continue
        it, eid = r.get("item"), r.get("element_id", 0)
        if it not in partidas or (eid and eid not in elementos):
            excluidos += 1
            agregar("referencia_inexistente", "inconsistencia", "Referencia inexistente",
                    "No se puede vincular el registro con la partida o el elemento exportado.",
                    it, [eid] if eid in elementos else [], ev)
            continue
        if eid and not any(p["item"] == it for p in elementos[eid]["partidas"]):
            excluidos += 1
            agregar("asignacion_inexistente", "inconsistencia", "Registro fuera de su asignación",
                    "La partida del registro no está asignada a este elemento.", it, [eid], ev)
            continue
        validos.append((r, q))

    acumulados, por_elemento, repetidos = defaultdict(Decimal), defaultdict(Decimal), defaultdict(list)
    for r, q in validos:
        acumulados[r["item"]] += q
        por_elemento[(r["element_id"], r["item"])] += q
        repetidos[(r["element_id"], r["item"], r["fecha"], q)].append(r)
    for (eid, it, f, q), grupo in repetidos.items():
        if len(grupo) > 1:
            agregar("posible_duplicado", "advertencia", "Registros coincidentes",
                    "Coinciden elemento, partida, fecha y cantidad. Pueden ser trabajos legítimos; "
                    "la coincidencia no demuestra duplicidad.", it, [eid] if eid else [],
                    {"fecha": f, "cantidad": str(q), "registros": [r["id"] for r in grupo]},
                    accion="Contrastar los partes originales. No eliminar automáticamente.")

    importe_revision = Decimal(0)
    for it, q in acumulados.items():
        p = partidas[it]
        referencia = numero(p["metrado"])
        if q > referencia + max(Decimal("0.000001"), abs(referencia) * Decimal("0.000001")):
            imp = moneda((q - referencia) * numero(p["pu"]))
            importe_revision += imp
            agregar("exceso_partida", "advertencia", "Acumulado superior a la referencia",
                    "El exceso puede corresponder a un cambio autorizado, un error o una referencia "
                    "desactualizada. No equivale a pérdida ni a costo real.", it,
                    [eid for (eid, item), v in por_elemento.items() if item == it and eid and v > 0],
                    {"referencia": str(referencia), "acumulado": str(q), "unidad": p["und"],
                     "pu": str(p["pu"]), "formula": "(acumulado - referencia) × PU",
                     "registros": [r["id"] for r, _ in validos if r["item"] == it]}, imp,
                    "Revisar registros y cambios autorizados antes de cerrar la valorización.")
        if q < 0:
            agregar("acumulado_negativo", "inconsistencia", "Acumulado negativo", "Revisar correcciones.",
                    it, evidencia={"acumulado": str(q)})

    cantidades_modelo = defaultdict(Decimal)
    revisados_fc = 0
    for eid, e in elementos.items():
        raw = crudos.get(eid, {})
        # Sin asumir resistencias por defecto: solo materiales explícitos.
        materiales = " | ".join(m.get("material") or "" for m in raw.get("materiales", []))
        fc = resistencia(materiales)
        for vinculo in e["partidas"]:
            it = vinculo["item"]
            if it not in partidas:
                agregar("partida_inexistente", "inconsistencia", "Vínculo a partida inexistente",
                        "El elemento referencia una partida ausente del presupuesto.", it, [eid],
                        {"asignacion": vinculo})
                continue
            p = partidas[it]
            cantidades_modelo[it] += numero(vinculo["metrado"])
            esperada = UNIDADES_CLASE.get(vinculo.get("clase"))
            if esperada and unidad(p["und"]) != esperada:
                agregar("unidad_incompatible", "inconsistencia", "Unidad incompatible con el criterio",
                        "La unidad no corresponde a la clase de medición declarada en el vínculo.",
                        it, [eid], {"clase": vinculo["clase"], "unidad": p["und"], "esperada": esperada})
            if vinculo.get("clase") == "concreto" and fc is not None:
                revisados_fc += 1
                fc_partida = resistencia(p["desc"])
                if fc_partida is not None and fc != fc_partida:
                    agregar("resistencia_distinta", "advertencia", "Material y partida con distinto f’c",
                            "Las especificaciones declaradas difieren. Revisar cuál está vigente.",
                            it, [eid], {"material": materiales, "fc_material": fc,
                                       "partida": p["desc"], "fc_partida": fc_partida},
                            accion="Verificar la especificación y consultar partidas compatibles.")
            q = por_elemento[(eid, it)]
            if q > numero(vinculo["metrado"]) + Decimal("0.000001"):
                agregar("exceso_elemento", "advertencia", "Elemento con mayor cantidad registrada",
                        "Detalle por elemento; no se suma de nuevo al importe de excesos por partida.",
                        it, [eid], {"referencia": str(vinculo["metrado"]), "acumulado": str(q)},
                        accion="Revisar el detalle sin duplicar el impacto de la partida.")
    for it, q in cantidades_modelo.items():
        p = partidas[it]
        ref = numero(p["metrado"])
        if abs(q - ref) > max(Decimal("0.01"), abs(ref) * tol):
            agregar("diferencia_modelo", "advertencia", "Modelo y presupuesto difieren",
                    "Puede existir alcance no modelado, criterio distinto o cobertura parcial. "
                    "No es una omisión confirmada.", it,
                    [e["id"] for e in elementos.values() if any(x["item"] == it for x in e["partidas"])],
                    {"cantidad_vinculada": str(q), "presupuesto": str(ref),
                     "unidad": p["und"], "tolerancia_relativa": str(tol)})
    orden = {"inconsistencia": 0, "advertencia": 1, "informacion": 2}
    hallazgos.sort(key=lambda h: (orden[h["nivel"]], -(h["importe"] or 0), h["item"] or "", h["id"]))
    return {
        "ok": True, "corte": corte, "hallazgos": hallazgos,
        "resumen": {"total": len(hallazgos), "inconsistencias": sum(h["nivel"] == "inconsistencia" for h in hallazgos),
                    "advertencias": sum(h["nivel"] == "advertencia" for h in hallazgos),
                    "importe_excesos_partida": float(importe_revision)},
        "cobertura": {"registros_total": len(registros), "registros_revisados": len(validos),
                      "registros_excluidos": excluidos, "registros_posteriores_al_corte": futuros,
                      "elementos": len(elementos), "partidas": len(partidas),
                      "vinculos_con_fc_comprobado": revisados_fc},
        "limites": [
            "No se dispone de costo real ni de un registro completo de cambios autorizados.",
            "La suma monetaria incluye solo excesos por partida; no suma duplicados ni detalles por elemento.",
            "No se evalúan geometrías solapadas como prueba de duplicación ni partidas sin BIM como omisiones.",
            "Precios, cuantías y criterios del caso incluyen supuestos; consultar las fuentes.",
        ],
    }


def comparar(a, b):
    """Descomposición exacta al céntimo con efecto de redondeo explícito."""
    def indice(version):
        out = {}
        for p in version["partidas"]:
            if p["item"] in out:
                raise ValueError("Código de partida repetido: " + p["item"])
            for k in ("metrado", "pu"):
                if numero(p[k]) < 0:
                    raise ValueError("La comparación requiere cantidades y precios no negativos.")
            out[p["item"]] = p
        return out
    aa, bb = indice(a), indice(b)
    filas = []
    totales = dict.fromkeys(("base", "nueva", "cantidad", "precio", "altas", "bajas", "no_comparable", "redondeo"), Decimal(0))
    for it in sorted(aa.keys() | bb.keys()):
        p, q = aa.get(it), bb.get(it)
        v1 = moneda(numero(p["metrado"]) * numero(p["pu"])) if p else Decimal(0)
        v2 = moneda(numero(q["metrado"]) * numero(q["pu"])) if q else Decimal(0)
        efectos = dict.fromkeys(("cantidad", "precio", "altas", "bajas", "no_comparable", "redondeo"), Decimal(0))
        if not p:
            tipo, efectos["altas"] = "Nueva", v2
        elif not q:
            tipo, efectos["bajas"] = "Retirada", -v1
        elif unidad(p["und"]) != unidad(q["und"]):
            tipo, efectos["no_comparable"] = "Unidad distinta", v2 - v1
        else:
            cambio = (p["desc"] != q["desc"] or numero(p["metrado"]) != numero(q["metrado"])
                      or numero(p["pu"]) != numero(q["pu"]))
            tipo = "Modificada" if cambio else "Sin cambio"
            efectos["cantidad"] = moneda((numero(q["metrado"]) - numero(p["metrado"])) * numero(p["pu"]))
            efectos["precio"] = moneda(numero(q["metrado"]) * (numero(q["pu"]) - numero(p["pu"])))
            efectos["redondeo"] = v2 - v1 - efectos["cantidad"] - efectos["precio"]
        totales["base"] += v1
        totales["nueva"] += v2
        for k, v in efectos.items():
            totales[k] += v
        filas.append({"item": it, "desc": (q or p)["desc"], "tipo": tipo,
                      "a": p, "b": q, "base": float(v1), "nueva": float(v2),
                      "delta": float(v2-v1), **{k: float(v) for k, v in efectos.items()}})
    delta = totales["nueva"] - totales["base"]
    componentes = sum(v for k, v in totales.items() if k not in ("base", "nueva"))
    return {"ok": True, "a": a["fuente"], "b": b["fuente"],
            "totales": {k: float(v) for k, v in totales.items()}, "delta": float(delta),
            "reconciliado": delta == componentes, "filas": filas,
            "metodo": "ΔQ × PU anterior + Q nueva × ΔPU; altas, bajas, unidades distintas y redondeo separados.",
            "limite": "Se comparan códigos de partida. Un código renombrado aparece como baja y alta; "
                      "no se infieren causas contractuales ni cambios geométricos."}
