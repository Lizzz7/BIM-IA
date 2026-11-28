"""Capa 3 · LLM: convierte un hallazgo (con su evidencia) en una observación técnica para el expediente.

El LLM NO calcula nada: recibe el hallazgo ya calculado y solo redacta. Su salida pasa por:
  1. esquema JSON (campos obligatorios, longitudes),
  2. verificador de números (todo número debe existir en la evidencia),
  3. si falla dos veces -> se usa la plantilla determinista y se marca así.
Se guarda en caché por (hallazgo, versión de datos, modelo): 100 usuarios abriendo el mismo hallazgo = 1 llamada.
"""
import json
import threading

from . import bitacora, llm
from . import datos as D
from .verificador import verificar

ESQUEMA = {
    "type": "object",
    "required": ["observacion", "accion", "responsable", "afecta_valorizacion"],
    "properties": {
        "observacion": {"type": "string", "maxLength": 600},
        "accion": {"type": "string", "maxLength": 400},
        "responsable": {"type": "string", "enum": ["Modelador BIM", "Costos y presupuestos", "Residente de obra", "Supervisión", "Ingeniero estructural"]},
        "afecta_valorizacion": {"type": "boolean"},
    },
}

SISTEMA = """Eres un ingeniero civil peruano, especialista en costos, metrados y valorizaciones de obra (S10, RNE).
Revisas hallazgos de un auditor automático sobre un modelo BIM de Revit y su presupuesto.
Reglas estrictas:
- Usa SOLO los datos del hallazgo. No inventes cantidades, precios, normas ni artículos.
- Todo número que escribas debe aparecer tal cual en los datos (puedes redondear a 2 decimales).
- No repitas el título; explica la causa técnica probable y su efecto en el metrado o el costo.
- 'accion' es una instrucción concreta y verificable para corregir (en Revit, en el presupuesto o en obra).
- Si el método es 'machine learning', dilo como sospecha a confirmar, no como certeza.
- Español técnico, frases cortas, sin saludo."""

_cache_lock = threading.Lock()
_en_curso = {}                    # clave -> threading.Lock: si 20 usuarios piden lo mismo, 1 llama y 19 esperan


def _ruta_cache():
    p = D.estado() / "cache" / f"narraciones_{D.huellas()['version_datos']}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


_memoria = {}


def _leer_cache():
    """Caché en memoria (respaldada en disco): se lee el archivo una sola vez por modelo y versión de datos."""
    p = _ruta_cache()
    if str(p) not in _memoria:
        _memoria[str(p)] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _memoria[str(p)]


def plantilla(h):
    v = h["evidencia"]["valores"]
    imp = h.get("impacto_soles")
    r = h["regla"]
    if r == "R01":
        return {"observacion": f"Los sólidos se intersectan sin estar unidos en Revit, por lo que {v['volumen_m3']} m³ de concreto se miden en ambos elementos"
                               + (f" (≈ S/ {imp:,.2f} de costo directo duplicado)." if imp else "."),
                "accion": "Unir geometría en Revit dando prioridad al elemento vertical (placa/muro) y volver a exportar metrados.",
                "responsable": "Modelador BIM", "afecta_valorizacion": True}
    if r == "R02":
        return {"observacion": f"El nombre del tipo indica f'c={v['fc_tipo']} y el material estructural f'c={v['fc_material'][0]}; el presupuesto toma el material ({v['item_presupuestado']}).",
                "accion": "Confirmar con el proyecto estructural el f'c correcto y corregir el tipo o el material en Revit.",
                "responsable": "Ingeniero estructural", "afecta_valorizacion": True}
    if r == "R03":
        return {"observacion": f"Sin material asignado; el metrado asume f'c={v['fc_asumido']} por defecto.",
                "accion": "Asignar el material estructural correcto en Revit.", "responsable": "Modelador BIM", "afecta_valorizacion": True}
    if r == "R04":
        return {"observacion": f"El acumulado registrado ({v['acumulado']}) supera el metrado contractual del elemento ({v['contrato']}).",
                "accion": "Verificar el parte diario; si es real, sustentar como mayor metrado con la supervisión.",
                "responsable": "Residente de obra", "afecta_valorizacion": True}
    if r == "R04b":
        return {"observacion": "La alerta guardada se debe a la suma de fracciones diarias en coma flotante; el exceso está por debajo de la tolerancia de medición.",
                "accion": "Ignorar la alerta y aplicar tolerancia de medición en el complemento.", "responsable": "Costos y presupuestos", "afecta_valorizacion": False}
    if r == "R05":
        return {"observacion": f"La actividad {v['actividad']} registra avance sin avance previo de su predecesora {v['predecesora']}.",
                "accion": "Revisar el parte diario o el orden constructivo antes de valorizar.", "responsable": "Residente de obra", "afecta_valorizacion": True}
    if r == "R06":
        return {"observacion": f"El concreto de mayor f'c ({v['item_mayor_fc']}) cuesta menos que el de menor f'c ({v['item_menor_fc']}) porque sus análisis usan métodos distintos (ver recursos del APU).",
                "accion": "Uniformizar el método de vaciado en los APU o sustentar la diferencia.", "responsable": "Costos y presupuestos", "afecta_valorizacion": False}
    if r == "ML1":
        return {"observacion": f"Sospecha: por su geometría (lados {v['lado_menor_m']} × {v['lado_mayor_m']} m) el modelo lo reconoce como {v['grupo_sugerido']} con probabilidad {v['probabilidad']}.",
                "accion": "Revisar la clasificación del tipo en Revit y la partida asignada.", "responsable": "Ingeniero estructural", "afecta_valorizacion": True}
    if r == "D01":
        return {"observacion": f"El elemento tiene S/ {v['monto_registrado']:,.2f} de metrado registrado, pero en el escaneo del {v['fecha_escaneo']} "
                               f"el dron lo ve {'ausente' if v['estado_dron'] == 'no_construido' else 'solo en parte'}: no debe valorizarse sin verificar.",
                "accion": "Verificar en obra (foto o wincha) antes de cerrar la valorización; si no está ejecutado, anular el registro.",
                "responsable": "Supervisión", "afecta_valorizacion": True}
    if r == "D02":
        return {"observacion": "El dron ve construido un elemento cuyo apoyo no aparece en la nube: o el apoyo existe y no se vio, o hay un error de registro.",
                "accion": "Revisar en el visor de la nube y confirmar el estado del apoyo en obra.", "responsable": "Residente de obra", "afecta_valorizacion": False}
    return {"observacion": h["titulo"], "accion": "Revisar.", "responsable": "Supervisión", "afecta_valorizacion": False}


def narrar(h, forzar=False):
    clave = f"{D.actual().id}|{h['id']}|{llm.MODELO}"
    with _cache_lock:
        if not forzar and clave in _leer_cache():
            return {**_leer_cache()[clave], "cache": True}
        candado = _en_curso.setdefault(clave, threading.Lock())
    with candado:
        with _cache_lock:
            if not forzar and clave in _leer_cache():   # otro hilo la generó mientras esperábamos
                return {**_leer_cache()[clave], "cache": True}
        return _generar(h, clave)


def _generar(h, clave):
    entrada = {k: h[k] for k in ("regla", "nombre", "metodo", "titulo", "partidas", "impacto_soles", "confianza", "evidencia")}
    entrada["elementos"] = h["elementos"][:5]
    entrada["n_elementos"] = len(h["elementos"])
    entrada["partidas_desc"] = {i: D.partidas()[i]["desc"] for i in h["partidas"] if i in D.partidas()}
    fuentes = (entrada, D.elementos().get(h["elementos"][0], {}).get("tipo", "") if h["elementos"] else "")

    def chequeo(obj):
        v = verificar(obj["observacion"] + " " + obj["accion"], *fuentes)
        return [f"el número '{x}' no está en los datos del hallazgo" for x in v["sin_respaldo"]]

    meta = {"proveedor": "plantilla", "modelo": "plantilla"}
    try:
        obj, meta = llm.pedir_json(SISTEMA, json.dumps(entrada, ensure_ascii=False, indent=1), ESQUEMA, chequeo)
        origen = "llm" if meta["aceptado"] else "plantilla (el LLM no pasó la verificación)"
        if not meta["aceptado"]:
            obj = plantilla(h)
    except llm.ErrorLLM as e:
        obj, origen = plantilla(h), "plantilla" + ("" if not llm.disponible() else f" (error: {e})")
    ver = verificar(obj["observacion"] + " " + obj["accion"], *fuentes)
    out = {**obj, "origen": origen, "proveedor": meta.get("proveedor"), "modelo": meta.get("modelo"),
           "verificacion": ver, "huella_entrada": bitacora.huella(entrada), "version_datos": D.huellas()["version_datos"]}
    bitacora.anotar("narrar", hallazgo=h["id"], origen=origen, proveedor=meta.get("proveedor"), modelo=meta.get("modelo"),
                    huella_entrada=out["huella_entrada"], salida=obj, verificacion=ver,
                    intentos=meta.get("intentos"), ms=meta.get("ms"))
    if "error" in origen:              # fallo transitorio del proveedor: no se guarda, el próximo intento vuelve a llamar
        return out
    with _cache_lock:
        cache = _leer_cache()
        cache[clave] = out
        tmp = _ruta_cache().with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_ruta_cache())
    return out
