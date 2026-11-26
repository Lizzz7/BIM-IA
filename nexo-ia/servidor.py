"""Servidor local del prototipo NEXO OBRA, independiente de Revit.

Uso desde la raíz: python nexo-ia/servidor.py
"""
import argparse
from collections import defaultdict
from datetime import date
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import uuid
from urllib.parse import parse_qs, urlsplit

from nexo_ia.almacen import Almacen
from nexo_ia.datos import Exportaciones
from nexo_ia.demo import ESPERADOS, caso_controlado
from nexo_ia.motor import auditar, fecha_iso, numero
from nexo_ia.proveedor import ProveedorIA
from nexo_ia.semantica import sugerir
from nexo_ia.versiones import Versiones


class Aplicacion:
    def __init__(self, raiz, estado):
        self.exportacion = Exportaciones(raiz)
        self.almacen = Almacen(Path(estado) / (self.exportacion.proyecto_id + ".sqlite3"),
                               self.exportacion.iniciales)
        self.ia = ProveedorIA()
        self.versiones = Versiones(raiz, self.exportacion.modelo)

    def auditoria(self, caso="actual", corte=None):
        if caso not in ("actual", "controlado"):
            raise ValueError("Caso de revisión no válido.")
        base, regs, raw = self.exportacion.base, self.almacen.registros(), self.exportacion.crudos
        if caso == "controlado":
            base, regs, raw = caso_controlado(base)
            corte = "2027-03-20"
        r = auditar(base, regs, raw, corte)
        revisiones = self.almacen.revisiones()
        for h in r["hallazgos"]:
            h["revision"] = revisiones.get(h["id"], {"estado": "Pendiente", "motivo": ""})
        r["caso"] = caso
        r["fuentes"] = self.exportacion.base["fuentes"]
        r["ia"] = self.ia.estado()
        if caso == "controlado":
            obtenidos = {h["regla"] for h in r["hallazgos"]}
            r["validacion_controlada"] = {
                "esperados": sorted(ESPERADOS), "obtenidos": sorted(obtenidos),
                "coinciden": obtenidos == ESPERADOS,
                "aviso": "Caso SIMULADO con seis hallazgos esperados y dos registros válidos de control. "
                         "No acredita precisión en obras reales ni se guarda en los avances.",
            }
        return r

    def hallazgo(self, pedido):
        reporte = self.auditoria(pedido.get("caso", "actual"), pedido.get("corte"))
        h = next((h for h in reporte["hallazgos"] if h["id"] == pedido.get("hallazgo")), None)
        if not h:
            raise ValueError("El hallazgo cambió o ya no existe. Vuelve a analizar.")
        return h

    def registrar(self, pedido):
        f = fecha_iso(pedido.get("fecha"))
        simular = pedido.get("simular", False)
        if not isinstance(simular, bool):
            raise ValueError("El campo simular debe ser booleano.")
        registros = pedido.get("registros")
        if not isinstance(registros, list) or not 1 <= len(registros) <= 5000:
            raise ValueError("El lote debe contener entre 1 y 5000 registros.")
        clave = pedido.get("request_id")
        if not isinstance(clave, str) or not 1 <= len(clave) <= 100:
            raise ValueError("Falta el identificador de solicitud para evitar registros repetidos.")
        base = self.exportacion.base
        partidas = {p["item"]: p for p in base["partidas"]}
        elementos = {e["id"]: e for e in base["elementos"]}
        vinculadas = {p["item"] for e in elementos.values() for p in e["partidas"]}
        nuevos = []
        for r in registros:
            if not isinstance(r, dict) or isinstance(r.get("id"), bool) or not isinstance(r.get("id"), int):
                raise ValueError("Identificador de elemento no válido.")
            eid, it, cantidad = r["id"], r.get("item"), numero(r.get("cantidad"))
            if not cantidad or it not in partidas:
                raise ValueError("Cantidad cero o partida inexistente. No se guardó el lote.")
            if eid == 0:
                if it in vinculadas:
                    raise ValueError("La partida tiene elementos; registra por elemento.")
            elif eid not in elementos or not any(p["item"] == it for p in elementos[eid]["partidas"]):
                raise ValueError("Elemento y partida no corresponden.")
            nuevos.append({"element_id": eid, "item": it, "fecha": f, "cantidad": str(cantidad)})
        huella = hashlib.sha256(json.dumps([f, nuevos], sort_keys=True).encode()).hexdigest()

        def preparar(actuales):
            acumulados = defaultdict(lambda: numero(0))
            for r in actuales:
                acumulados[(r["element_id"], r["item"])] += numero(r["cantidad"])
            alertas, aplicados, tocados = [], [], set()
            for r in nuevos:
                eid, it = r["element_id"], r["item"]
                acumulados[(eid, it)] += numero(r["cantidad"])
                q = acumulados[(eid, it)]
                if q < 0:
                    raise ValueError("El acumulado quedaría negativo. No se guardó el lote.")
                ref = partidas[it]["metrado"] if not eid else next(
                    p["metrado"] for p in elementos[eid]["partidas"] if p["item"] == it)
                if q > numero(ref):
                    alertas.append(f"{eid or 'Partida'} / {it}: acumulado {q} supera la referencia {ref}.")
                aplicados.append({"id": eid, "item": it, "cantidad": float(numero(r["cantidad"])), "acumulado": float(q)})
                tocados.add(eid)
            datos = self.exportacion.panel(actuales + [
                {**r, "id": "nuevo", "fuente": "Registro local"} for r in nuevos])
            respuesta = {"ok": True, "simulado": simular, "guardado": not simular,
                         "aplicados": aplicados, "rechazados": [], "alertas": alertas,
                         "elementos": [{"id": e["id"], "registro": e["registro"], "obs": e["obs"]}
                                       for e in datos["elementos"] if e["id"] in tocados],
                         "registroGlobal": datos["registroGlobal"]}
            return nuevos, respuesta
        return self.almacen.registrar(clave, huella, preparar, simular)


class Manejador(BaseHTTPRequestHandler):
    server_version = "NexoLocal/1.0"

    def log_message(self, formato, *args):
        # No registrar cuerpos, claves, consultas ni contenido de documentos.
        print(f"{self.command} {urlsplit(self.path).path} · {args[1] if len(args) > 1 else ''}")

    def enviar(self, valor, codigo=200, tipo="application/json; charset=utf-8"):
        if isinstance(valor, str):
            data = valor.encode("utf-8")
        else:
            data = json.dumps(valor, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(data)

    def local(self):
        puerto = self.server.server_port
        hosts = {f"127.0.0.1:{puerto}", f"localhost:{puerto}"}
        if self.headers.get("Host") not in hosts:
            raise PermissionError("Host local no permitido.")
        origen = self.headers.get("Origin")
        if origen and origen not in {f"http://{h}" for h in hosts}:
            raise PermissionError("Origen no permitido.")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise PermissionError("Solicitud externa no permitida.")

    def cuerpo(self):
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise ValueError("El cuerpo debe ser application/json.")
        n = int(self.headers.get("Content-Length", "0"))
        if not 0 < n <= 1_000_000:
            raise ValueError("Cuerpo vacío o superior a 1 MB.")
        d = json.loads(self.rfile.read(n), parse_constant=lambda _: None)
        if not isinstance(d, dict):
            raise ValueError("Se esperaba un objeto JSON.")
        return d

    def do_GET(self):
        self.atender(False)

    def do_POST(self):
        self.atender(True)

    def atender(self, post):
        try:
            self.local()
            app = self.server.app
            url = urlsplit(self.path)
            ruta = url.path.rstrip("/")
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            p = self.cuerpo() if post else {}
            if not post and ruta in ("", "/index.html"):
                return self.enviar(app.exportacion.html(), tipo="text/html; charset=utf-8")
            if not post and ruta == "/favicon.ico":
                return self.enviar("", 204, "image/x-icon")
            if not post and ruta == "/api/ping":
                return self.enviar({"ok": True, "version": "1.0.0", "modo": "exportado"})
            if not post and ruta == "/api/datos":
                return self.enviar(app.exportacion.panel(app.almacen.registros()))
            if not post and ruta == "/api/geometria":
                return self.enviar(app.exportacion.geometria())
            if not post and ruta == "/api/estado":
                return self.enviar({"ok": True, "modo": "exportado", "ia": app.ia.estado(),
                                   "aviso": app.exportacion.base["advertencia"]})
            if not post and ruta == "/api/auditoria":
                return self.enviar(app.auditoria(q.get("caso", "actual"), q.get("corte")))
            if post and ruta == "/api/metrado":
                return self.enviar(app.registrar(p))
            if post and ruta == "/api/revision":
                h = app.hallazgo(p)
                return self.enviar(app.almacen.revisar(h["id"], p.get("estado"), p.get("motivo")))
            if post and ruta == "/api/explicar":
                return self.enviar(app.ia.explicar(app.hallazgo(p)))
            if post and ruta == "/api/sugerencias":
                return self.enviar(sugerir(app.exportacion.base, app.exportacion.crudos,
                                           int(p.get("element_id", 0)), p.get("clase"), app.ia,
                                           usar_ia=p.get("usar_ia") is True))
            if not post and ruta == "/api/versiones":
                return self.enviar({"ok": True, "versiones": app.versiones.listar()})
            if not post and ruta == "/api/comparacion":
                return self.enviar(app.versiones.comparar(q.get("a", "v3"), q.get("b", "v4")))
            if not post and ruta == "/api/recursos":
                v = app.versiones.leer(q.get("version", "v4"))
                return self.enviar({"ok": True, "fuente": v["fuente"], "recursos": list(v["recursos"].values())})
            if post and ruta == "/api/escenario":
                return self.enviar(app.versiones.escenario(p.get("version", "v4"), p.get("codigo"), p.get("porcentaje")))
            if post and ruta == "/api/escenario/propuesta":
                v = app.versiones.leer(p.get("version", "v4"))
                return self.enviar(app.ia.interpretar_escenario(p.get("texto"), v["recursos"], p.get("usar_ia") is True))
            return self.enviar({"ok": False, "error": "Ruta no disponible."}, 404)
        except PermissionError as e:
            self.enviar({"ok": False, "error": str(e)}, 403)
        except (ValueError, KeyError, TypeError) as e:
            mensaje = str(e) if isinstance(e, ValueError) else "Campos de solicitud o datos no válidos."
            self.enviar({"ok": False, "error": mensaje}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.enviar({"ok": False, "error": "Error interno. Revisa las fuentes y la configuración local."}, 500)


def crear_servidor(raiz, estado, puerto=8771):
    app = Aplicacion(raiz, estado)
    servidor = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    servidor.app = app
    return servidor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--puerto", type=int, default=8771)
    parser.add_argument("--estado", type=Path, help="Carpeta de SQLite; por defecto .nexo-local en la raíz.")
    args = parser.parse_args()
    raiz = Path(__file__).resolve().parent.parent
    servidor = crear_servidor(raiz, args.estado or raiz / ".nexo-local", args.puerto)
    print(f"NEXO OBRA independiente de Revit: http://127.0.0.1:{servidor.server_port}/")
    print("Datos académicos de prueba. Los originales no se modifican. Ctrl+C para detener.")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
