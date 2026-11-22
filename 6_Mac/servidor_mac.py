"""NEXO OBRA (NO) · Emulador del complemento de Revit para trabajar en Mac/Linux SIN Revit.

Hace lo mismo que NexoObraNO (Servidor.cs + Escritura.cs), pero leyendo los datos ya exportados:
  GET  /                 1_Panel/index.html
  GET  /api/ping
  GET  /api/datos        datos del modelo (sacados de la instantánea) + registros de metrado actuales
  GET  /api/geometria    mallas 3D (sacadas de la instantánea)
  POST /api/metrado      mismas validaciones que Escritura.Registrar; guarda en registros_<modelo>.json

La primera vez extrae datos y geometría de 5_Documentacion/Compartir/NEXO_OBRA_solo_lectura.html
a 6_Mac/cache/. Solo usa la librería estándar de Python 3.9+.

Uso:  python3 6_Mac/servidor_mac.py         → abre http://127.0.0.1:8770
"""
import json
import re
import shutil
import sys
import threading
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PUERTO = 8770
RAIZ = Path(__file__).resolve().parent.parent
PANEL = RAIZ / "1_Panel" / "index.html"
INSTANTANEA = RAIZ / "5_Documentacion" / "Compartir" / "NEXO_OBRA_solo_lectura.html"
CACHE = Path(__file__).resolve().parent / "cache"
CANDADO = threading.Lock()


# ---------------------------------------------------------------- datos base
def extraer_instantanea():
    CACHE.mkdir(exist_ok=True)
    base, geo = CACHE / "datos_base.json", CACHE / "geometria.json"
    if base.exists() and geo.exists():
        return
    print("Extrayendo datos y geometría de la instantánea (solo la primera vez)…")
    html = INSTANTANEA.read_text(encoding="utf-8")
    m = re.search(r"window\.NEXO_SNAPSHOT=(\{.*?\});</script>", html, re.S)
    if not m:
        sys.exit("No encontré window.NEXO_SNAPSHOT en la instantánea.")
    snap = json.loads(m.group(1))
    datos = snap["datos"]
    for e in datos["elementos"]:            # los registros viven aparte, como en el complemento
        e["registro"], e["obs"] = "", ""
    datos["registroGlobal"] = ""
    base.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    geo.write_text(json.dumps(snap["geo"], ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


BASE = None


def base():
    global BASE
    if BASE is None:
        BASE = json.loads((CACHE / "datos_base.json").read_text(encoding="utf-8"))
    return BASE


def ruta_registros():
    return RAIZ / "3_Modelo_y_parametros" / f"registros_{base()['modelo']}.json"


def leer_registros():
    r = ruta_registros()
    if not r.exists():
        return {"elementos": {}, "global": ""}
    o = json.loads(r.read_text(encoding="utf-8"))
    o.setdefault("elementos", {})
    o.setdefault("global", "")
    return o


def guardar_registros(o):
    r = ruta_registros()
    tmp = r.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")
    if r.exists():
        d = r.parent / "respaldos_registros"
        d.mkdir(exist_ok=True)
        copia = d / f"{r.stem}_{date.today().isoformat()}.json"
        if not copia.exists():
            shutil.copy(r, copia)
    tmp.replace(r)


def sumas(reg):
    d = {}
    for x in (reg or "").split(";"):
        p = x.split("|")
        if len(p) == 3:
            try:
                d[p[1]] = d.get(p[1], 0.0) + float(p[2])
            except ValueError:
                pass
    return d


def datos_actuales():
    d = json.loads(json.dumps(base()))      # copia
    reg = leer_registros()
    for e in d["elementos"]:
        n = reg["elementos"].get(str(e["id"]))
        if n:
            e["registro"], e["obs"] = n.get("registro", ""), n.get("obs", "")
    d["registroGlobal"] = reg.get("global", "")
    d["archivoRegistros"] = str(ruta_registros())
    return d


# ---------------------------------------------------------------- escritura (port de Escritura.Registrar)
def registrar(ped):
    try:
        f = datetime.strptime(ped.get("fecha", ""), "%Y-%m-%d")
    except ValueError:
        raise ValueError("Fecha no válida (aaaa-mm-dd).")
    fs, fdmy = f.strftime("%Y-%m-%d"), f.strftime("%d/%m/%Y")
    b = base()
    partidas = {p["item"]: p for p in b["partidas"]}
    elems = {e["id"]: e for e in b["elementos"]}
    con_elementos = {p["item"] for e in b["elementos"] for p in e["partidas"]}
    aplicados, rechazados, alertas, tocados = [], [], [], set()
    with CANDADO:
        reg = leer_registros()
        E = reg["elementos"]
        for r in ped.get("registros") or []:
            rid, item = int(r.get("id") or 0), r.get("item") or ""
            try:
                q = float(r.get("cantidad"))
            except (TypeError, ValueError):
                q = 0.0
            if q == 0 or q != q:
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
            nodo = E.get(str(rid)) or {"registro": "", "obs": ""}
            nuevo, cont = sumas(nodo["registro"]).get(item, 0.0) + q, pe["metrado"]
            if nuevo < -1e-9:
                rechazados.append({"id": rid, "item": item, "motivo": f"El acumulado quedaría negativo ({nuevo:.3f})."}); continue
            nodo["registro"] += f"{fs}|{item}|{q!r};"
            if nuevo > cont * (1 + 1e-6) + 1e-9:
                msg = f"{fdmy} · mayor metrado {item}: acumulado {nuevo:.3f} {und} > contrato {cont:.3f} {und}"
                alertas.append(f"Elemento {rid} ({de['tipo']}): {msg}")
                nodo["obs"] = (nodo["obs"] + " | " if nodo.get("obs") else "") + msg
            E[str(rid)] = nodo
            tocados.add(rid)
            aplicados.append({"id": rid, "item": item, "cantidad": q, "acumulado": nuevo, "contrato": cont})
        simular = bool(ped.get("simular"))
        if not simular and aplicados:
            guardar_registros(reg)
        return {"ok": True, "simulado": simular, "guardado": not simular and bool(aplicados),
                "aplicados": aplicados, "rechazados": rechazados, "alertas": alertas, "notas": [],
                "elementos": [] if simular else [{"id": i, **E[str(i)]} for i in tocados],
                "registroGlobal": reg.get("global", "")}


# ---------------------------------------------------------------- HTTP
class Manejador(BaseHTTPRequestHandler):
    def log_message(self, fmt, *a):
        sys.stderr.write("  " + (fmt % a) + "\n")

    def _enviar(self, codigo, cuerpo, tipo="application/json; charset=utf-8"):
        if not isinstance(cuerpo, (bytes, bytearray)):
            cuerpo = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        ruta = self.path.split("?")[0].rstrip("/").lower()
        try:
            if ruta in ("", "/index.html"):
                self._enviar(200, PANEL.read_bytes(), "text/html; charset=utf-8")
            elif ruta == "/api/ping":
                self._enviar(200, {"ok": True, "version": "mac-emulador"})
            elif ruta == "/api/datos":
                self._enviar(200, datos_actuales())
            elif ruta == "/api/geometria":
                self._enviar(200, (CACHE / "geometria.json").read_bytes())
            else:
                self._enviar(404, {"ok": False, "error": f"No existe GET {self.path}"})
        except Exception as ex:          # noqa: BLE001
            self._enviar(500, {"ok": False, "error": str(ex)})

    def do_POST(self):
        ruta = self.path.split("?")[0].rstrip("/").lower()
        try:
            n = int(self.headers.get("Content-Length") or 0)
            ped = json.loads(self.rfile.read(n) or b"{}")
            if ruta == "/api/metrado":
                self._enviar(200, registrar(ped))
            else:
                self._enviar(404, {"ok": False, "error": f"No existe POST {self.path}"})
        except ValueError as ex:
            self._enviar(400, {"ok": False, "error": str(ex)})
        except Exception as ex:          # noqa: BLE001
            self._enviar(500, {"ok": False, "error": str(ex)})


if __name__ == "__main__":
    extraer_instantanea()
    srv = ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador)
    print(f"NEXO OBRA (emulador sin Revit) · {base()['modelo']} · {len(base()['elementos'])} elementos")
    print(f"Abre http://127.0.0.1:{PUERTO}   (Ctrl+C para salir)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
