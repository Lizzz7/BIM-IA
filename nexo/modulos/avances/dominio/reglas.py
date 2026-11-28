"""Registro de metrado ejecutado: port de Escritura.Registrar (C#) del complemento, con las mismas validaciones.

  aplicar(reg, ped)  -> función PURA: devuelve (registros nuevos, resultado). No lee ni escribe disco.
  registrar(ped)     -> lee registros.json, aplica y guarda (salvo ped["simular"]) con candado por modelo.

La simulación paso a paso usa aplicar() sobre una copia en memoria: así ve las mismas alertas que vería el
complemento sin guardar nada.
"""
import json
import math
from datetime import datetime


def sumas(reg):
    d = {}
    for linea in (reg or "").split(";"):
        p = linea.split("|")
        if len(p) == 3:
            d[p[1]] = d.get(p[1], 0.0) + float(p[2])
    return d


def aplicar(reg, ped, partidas, elems):
    """Aplica los registros de `ped` sobre una COPIA de `reg`. Devuelve (reg_nuevo, resultado)."""
    try:
        f = datetime.strptime(ped.get("fecha", ""), "%Y-%m-%d")
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Fecha no válida (aaaa-mm-dd).")
    fs, fdmy = f.strftime("%Y-%m-%d"), f.strftime("%d/%m/%Y")
    con_elementos = {p["item"] for e in elems.values() for p in e["partidas"]}
    aplicados, rechazados, alertas, tocados = [], [], [], set()
    reg = json.loads(json.dumps(reg))
    reg.setdefault("elementos", {})
    reg.setdefault("global", "")
    E = reg["elementos"]
    for r in ped.get("registros") or []:
        rid, item = int(r.get("id") or 0), r.get("item") or ""
        try:
            q = float(r.get("cantidad"))
        except (TypeError, ValueError):
            q = 0.0
        if q == 0 or not math.isfinite(q) or isinstance(r.get("cantidad"), bool):
            rechazados.append({"id": rid, "item": item, "motivo": "Cantidad 0 o no válida."}); continue
        part = partidas.get(item)
        if not part:
            rechazados.append({"id": rid, "item": item, "motivo": "La partida no existe en el presupuesto."}); continue
        und = part["und"]
        if rid == 0:
            if item in con_elementos:
                rechazados.append({"id": 0, "item": item, "motivo": "Esta partida tiene elementos: registra por elemento o por partida completa."}); continue
            g = reg.get("global", "")
            nuevo, contrato = sumas(g).get(item, 0.0) + q, part["metrado"]
            if nuevo < -1e-9:
                rechazados.append({"id": 0, "item": item, "motivo": f"El acumulado quedaría negativo ({nuevo:.3f})."}); continue
            reg["global"] = g + f"{fs}|{item}|{q!r};"
            if nuevo > contrato * (1 + 1e-6) + 1e-9:
                alertas.append(f"{item}: acumulado {nuevo:.3f} {und} supera el contrato ({contrato:.3f} {und}).")
            aplicados.append({"id": 0, "item": item, "cantidad": q, "acumulado": nuevo, "contrato": contrato}); continue
        de = elems.get(rid)
        if not de:
            rechazados.append({"id": rid, "item": item, "motivo": "El elemento no está en los datos del cronograma."}); continue
        pe = next((p for p in de["partidas"] if p["item"] == item), None)
        if not pe:
            rechazados.append({"id": rid, "item": item, "motivo": "Esa partida no corresponde a este elemento."}); continue
        nodo = dict(E.get(str(rid)) or {"registro": "", "obs": ""})
        nuevo, cont = sumas(nodo["registro"]).get(item, 0.0) + q, pe["metrado"]
        if nuevo < -1e-9:
            rechazados.append({"id": rid, "item": item, "motivo": f"El acumulado quedaría negativo ({nuevo:.3f})."}); continue
        nodo["registro"] = nodo["registro"] + f"{fs}|{item}|{q!r};"
        if nuevo > cont * (1 + 1e-6) + 1e-9:
            msg = f"{fdmy} · mayor metrado {item}: acumulado {nuevo:.3f} {und} > contrato {cont:.3f} {und}"
            alertas.append(f"Elemento {rid} ({de['tipo']}): {msg}")
            nodo["obs"] = (nodo["obs"] + " | " if nodo.get("obs") else "") + msg
        E[str(rid)] = nodo
        tocados.add(rid)
        aplicados.append({"id": rid, "item": item, "cantidad": q, "acumulado": nuevo, "contrato": cont})
    monto = round(sum(a["cantidad"] * partidas[a["item"]]["pu"] for a in aplicados), 2)
    return reg, {"aplicados": aplicados, "rechazados": rechazados, "alertas": alertas, "tocados": tocados, "monto_cd": monto}
