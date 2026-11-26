"""Caso sintético pequeño con resultados esperados. No toca la obra ni entrena modelos."""
from copy import deepcopy


def caso_controlado(base):
    # IDs reales solo para localizar las geometrías; cantidades/precios son ficticios.
    ids = [e["id"] for e in base["elementos"][:2]]
    partidas = [
        {"item": "D.01", "desc": "CONCRETO f'c=280 EN ZAPATAS", "und": "m3", "metrado": 10, "pu": 300},
        {"item": "D.02", "desc": "CONCRETO f'c=350 EN ZAPATAS", "und": "m3", "metrado": 10, "pu": 350},
        {"item": "D.03", "desc": "ACERO DE REFUERZO", "und": "m3", "metrado": 20, "pu": 5},
    ]
    copia = deepcopy(base)
    copia["partidas"] = partidas
    copia["elementos"] = [
        {"id": ids[0], "tipo": "Zapata SIMULADA", "grupo": "ZAP", "partidas": [
            {"item": "D.01", "clase": "concreto", "metrado": 10},
            {"item": "D.03", "clase": "acero", "metrado": 20}]},
        {"id": ids[1], "tipo": "Zapata SIMULADA", "grupo": "ZAP", "partidas": [
            {"item": "D.02", "clase": "concreto", "metrado": 10}]},
    ]
    registros = [
        {"id": "demo:1", "element_id": ids[0], "item": "D.01", "fecha": "2027-03-20", "cantidad": "6"},
        {"id": "demo:2", "element_id": ids[0], "item": "D.01", "fecha": "2027-03-20", "cantidad": "6"},
        {"id": "demo:3", "element_id": 0, "item": "NO_EXISTE", "fecha": "2027-03-20", "cantidad": "1"},
        {"id": "demo:4", "element_id": ids[1], "item": "D.02", "fecha": "2027-03-19", "cantidad": "2"},
        {"id": "demo:5", "element_id": ids[1], "item": "D.02", "fecha": "2027-03-20", "cantidad": "3"},
    ]
    crudos = {i: {"materiales": [{"material": "Concreto f'c=280"}]} for i in ids}
    return copia, registros, crudos


ESPERADOS = {"referencia_inexistente", "posible_duplicado", "exceso_partida",
             "exceso_elemento", "unidad_incompatible", "resistencia_distinta"}
