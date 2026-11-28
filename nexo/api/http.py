"""NEXO OBRA + IA · servidor único (Mac/Linux/Windows, sin Revit; local o en la nube).

1. Emula el complemento de Revit (mismas rutas que NexoObraNO): /api/ping, /api/datos, /api/geometria, POST /api/metrado.
2. Varios modelos con versiones: el modelo de cada petición se elige con ?modelo=&version= o la cookie nexo_modelo.
3. Capa de IA: /api/ia/*.
4. Sirve el panel ORIGINAL del repo e inyecta /ia/nexo_ia.js al enviarlo (el archivo del repo no se modifica).

Variables de entorno
  NEXO_REPO, NEXO_MODELOS, NEXO_ESTADO          rutas (ver nexo_ia/datos.py)
  PORT / NEXO_PUERTO, NEXO_HOST                  dónde escuchar (en la nube: NEXO_HOST=0.0.0.0)
  NEXO_SOLO_LECTURA=1                            nadie registra metrado ni decide (link de vitrina)
  NEXO_TOKEN=<secreto>                           para escribir hay que entrar una vez con /entrar?token=<secreto>
  NEXO_TOKEN_ADMIN=<secreto>                     para publicar versiones: POST /api/admin/publicar (cabecera X-Nexo-Admin)
  NEXO_LLM_POR_MINUTO=30                         límite de llamadas a la IA por IP
  NEXO_MAX_NUBE_MB=400                           tamaño máximo de una nube de puntos o IFC subido (avance por dron)
  NEXO_LLM y las del proveedor                   ver nexo_ia/llm.py
"""
import gzip
import hmac
import io
import json
import os
import re
import shutil
import sys
import threading
import time
import zipfile
from collections import defaultdict, deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from nexo_ia import (auditor, bitacora, consultas, costos, escaneo, exportar, ifc_modelo, llm, narrador, nube_io, parte_diario,
                     simulacion, sintetico)
from nexo_ia.metrado import guardar_registros, registrar, sumas  # noqa: F401  (se re-exportan: pruebas y scripts)
from nexo_ia import datos as D
from nexo import bootstrap

AQUI = Path(__file__).resolve().parents[2] / "nexo-ia"
JS = Path(__file__).resolve().parents[1] / "web" / "nexo_ia.js"
HOST = os.environ.get("NEXO_HOST", "127.0.0.1")
PUERTO = int(os.environ.get("PORT") or os.environ.get("NEXO_PUERTO") or 8770)
SOLO_LECTURA = os.environ.get("NEXO_SOLO_LECTURA") == "1"
TOKEN = os.environ.get("NEXO_TOKEN", "")
TOKEN_ADMIN = os.environ.get("NEXO_TOKEN_ADMIN", "")
LLM_POR_MINUTO = int(os.environ.get("NEXO_LLM_POR_MINUTO", "30"))
MAX_ZIP = int(os.environ.get("NEXO_MAX_MB", "200")) * 1024 * 1024
MAX_NUBE = int(os.environ.get("NEXO_MAX_NUBE_MB", "400")) * 1024 * 1024
ID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

candado = D.candado                          # un candado por (modelo, uso): un modelo no bloquea a otro


# ---------------------------------------------------------------- emulación del complemento
def datos_actuales():
    m = D.actual()
    d = json.loads(json.dumps(D.datos_base()))
    reg = D.leer_registros()
    for e in d["elementos"]:
        n = reg["elementos"].get(str(e["id"]))
        if n:
            e["registro"], e["obs"] = n.get("registro", ""), n.get("obs", "")
    d["registroGlobal"] = reg.get("global", "")
    d["archivoRegistros"] = f"estado/{m.id}/registros.json"
    d["nexo"] = {"modelo": m.id, "version": m.version}
    return d


# ---------------------------------------------------------------- IA (cachés por modelo)
_aud = {}


def auditoria():
    """Se recalcula solo si cambian la versión de datos o los registros. Candado propio por modelo:
    mientras se audita, el resto del servidor (datos, 3D, otros modelos) sigue respondiendo."""
    m = D.actual()
    ult = D.estado() / "escaneo_ultimo.json"
    clave = (m.version, m.huellas["version_datos"], D.ruta_registros().stat().st_mtime_ns,
             ult.stat().st_mtime_ns if ult.exists() else 0)
    with candado("auditoria"):
        c = _aud.get(m.id)
        if not c or c[0] != clave:
            t = time.time()
            v = auditor.auditar()
            v["calculado_en_ms"] = int((time.time() - t) * 1000)
            _aud[m.id] = c = (clave, v)
            bitacora.anotar("auditoria", n=len(v["hallazgos"]), impacto=v["impacto_total_soles"], ms=v["calculado_en_ms"])
    a = dict(c[1])
    dec = bitacora.decisiones()
    a["hallazgos"] = [dict(h, decision=dec.get(h["id"])) for h in a["hallazgos"]]
    a["modelo"] = m.resumen()
    return a


def hallazgo_por_id(hid):
    h = next((x for x in auditoria()["hallazgos"] if x["id"] == hid), None)
    if not h:
        raise ValueError(f"No existe el hallazgo {hid} en la versión actual de datos.")
    return h


# ---------------------------------------------------------------- publicar una versión (zip)
def publicar(cuerpo: bytes, autor: str):
    """Recibe un zip con modelo.json + archivos exportados por el complemento. Crea modelos/<id>/<version>/.
    Las versiones son inmutables: publicar dos veces la misma versión se rechaza."""
    if len(cuerpo) > MAX_ZIP:
        raise ValueError(f"El zip supera {MAX_ZIP // 2**20} MB")
    z = zipfile.ZipFile(io.BytesIO(cuerpo))
    nombres = z.namelist()
    raiz = ""
    if "modelo.json" not in nombres:                  # admite zip con una carpeta raíz
        cands = [n for n in nombres if n.endswith("/modelo.json") and n.count("/") == 1]
        if not cands:
            raise ValueError("El zip no contiene modelo.json")
        raiz = cands[0][:-len("modelo.json")]
    man = json.loads(z.read(raiz + "modelo.json"))
    mid, ver = str(man.get("id", "")), str(man.get("version", ""))
    if not (ID_OK.match(mid) and ID_OK.match(ver)):
        raise ValueError("id y version deben ser texto simple (letras, números, . _ -)")
    destino = D.MODELOS / mid / ver
    if destino.exists():
        raise FileExistsError(f"La versión {mid} {ver} ya existe; publica una versión nueva.")
    tmp = D.MODELOS / mid / f".subiendo-{ver}-{threading.get_ident()}"
    tmp.mkdir(parents=True)
    try:
        for n in nombres:
            if not n.startswith(raiz) or n.endswith("/"):
                continue
            rel = Path(n[len(raiz):])
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError(f"Ruta no permitida en el zip: {n}")
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as src, open(tmp / rel, "wb") as dst:
                shutil.copyfileobj(src, dst)
        man.setdefault("publicado", time.strftime("%Y-%m-%dT%H:%M:%S"))
        man.setdefault("autor", autor)
        (tmp / "modelo.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        falt = D._modelo_de_carpeta(tmp).faltantes()
        if falt:
            raise ValueError(f"Faltan archivos en la versión: {falt}")
        tmp.rename(destino)                           # aparece completa o no aparece
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return {"id": mid, "version": ver, "ruta": str(destino)}


# ---------------------------------------------------------------- límite de llamadas a la IA
_llamadas = defaultdict(deque)
_ll_lock = threading.Lock()


def limitar(ip, pesado=False):
    """Límite por IP para el LLM y, siempre, para lo que consume mucha CPU (escaneo, simulación)."""
    if not (pesado or llm.disponible()):
        return
    ahora = time.time()
    with _ll_lock:
        q = _llamadas[ip]
        while q and ahora - q[0] > 60:
            q.popleft()
        if len(q) >= LLM_POR_MINUTO:
            raise PermissionError(f"Demasiadas consultas a la IA ({LLM_POR_MINUTO}/min). Espera un momento.")
        q.append(ahora)


# ---------------------------------------------------------------- HTTP
_bytes = {}
_bytes_lock = threading.Lock()


def cacheado(nombre, clave, generar):
    """Guarda (crudo, gzip) por modelo y clave: 100 usuarios pidiendo lo mismo = 1 serialización y 1 compresión."""
    k = (D.actual().id, D.actual().version, nombre)
    with _bytes_lock:
        c = _bytes.get(k)
        if c and c[0] == clave:
            return c[1], c[2]
    crudo = generar()
    if not isinstance(crudo, (bytes, bytearray)):
        crudo = json.dumps(crudo, ensure_ascii=False, default=str).encode("utf-8")
    gz = gzip.compress(crudo, 6)
    with _bytes_lock:
        _bytes[k] = (clave, crudo, gz)
    return crudo, gz


def panel_html():
    html = D.PANEL.read_text(encoding="utf-8")
    inyeccion = '<script src="/ia/nexo_ia.js"></script>\n<script src="/ia/cotizaciones.js"></script>\n'
    i = html.lower().rfind("</body>")
    return (html[:i] + inyeccion + html[i:]) if i >= 0 else html + inyeccion


class Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        sys.stderr.write(f"  {self.ip()} {fmt % a}\n")

    # ---------------- utilidades
    def ip(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def cookies(self):
        out = {}
        for parte in (self.headers.get("Cookie") or "").split(";"):
            if "=" in parte:
                k, v = parte.strip().split("=", 1)
                out[k] = v
        return out

    def puede_escribir(self):
        if SOLO_LECTURA:
            return False
        if not TOKEN:
            return True                                       # modo local: sin token configurado
        dado = self.cookies().get("nexo_token") or self.headers.get("X-Nexo-Token") or ""
        return hmac.compare_digest(dado, TOKEN)

    def exigir_escritura(self):
        if not self.puede_escribir():
            raise PermissionError("Solo lectura: entra con el enlace de acceso del equipo para registrar o decidir.")

    def elegir_modelo(self, q):
        ck = self.cookies()
        mid = (q.get("modelo") or [ck.get("nexo_modelo")])[0]
        ver = (q.get("version") or [ck.get("nexo_version")])[0]
        return D.usar(mid, ver or None)

    def _cabeceras(self, codigo, tipo, largo, cache="no-store", extra=None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(largo))

    def _enviar_cache(self, par, tipo="application/json; charset=utf-8", cache="no-store", extra=None):
        crudo, gz = par
        usa_gz = "gzip" in (self.headers.get("Accept-Encoding") or "")
        cuerpo = gz if usa_gz else crudo
        self._cabeceras(200, tipo, len(cuerpo), cache, {**(extra or {}), **({"Content-Encoding": "gzip"} if usa_gz else {})})
        self.end_headers()
        self.wfile.write(cuerpo)

    def _enviar(self, codigo, cuerpo, tipo="application/json; charset=utf-8", cache="no-store", extra=None):
        if not isinstance(cuerpo, (bytes, bytearray)):
            cuerpo = json.dumps(cuerpo, ensure_ascii=False, default=str).encode("utf-8")
        gz = len(cuerpo) > 2048 and "gzip" in (self.headers.get("Accept-Encoding") or "")
        if gz:
            cuerpo = gzip.compress(cuerpo, 5)
        self._cabeceras(codigo, tipo, len(cuerpo), cache, {**(extra or {}), **({"Content-Encoding": "gzip"} if gz else {})})
        self.end_headers()
        self.wfile.write(cuerpo)

    def _error(self, ex):
        codigo = 403 if isinstance(ex, PermissionError) else 409 if isinstance(ex, FileExistsError) else \
            400 if isinstance(ex, (ValueError, KeyError, zipfile.BadZipFile, json.JSONDecodeError)) else \
            404 if isinstance(ex, LookupError) else 500
        self._enviar(codigo, {"ok": False, "error": f"{ex}" if codigo < 500 else f"{type(ex).__name__}: {ex}"})

    # ---------------- GET
    def do_GET(self):
        u = urlparse(self.path)
        ruta, q = u.path.rstrip("/").lower(), parse_qs(u.query)
        try:
            if ruta == "/entrar":                         # enlace de acceso del equipo: deja una cookie y vuelve al panel
                ok = TOKEN and hmac.compare_digest((q.get("token") or [""])[0], TOKEN)
                self._cabeceras(302, "text/plain", 0, extra={"Location": "/",
                                **({"Set-Cookie": f"nexo_token={TOKEN}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"} if ok else {})})
                self.end_headers()
                return
            m = self.elegir_modelo(q)
            if ruta in ("", "/index.html"):
                extra = {}
                if "modelo" in q:                          # ?modelo=X deja la elección guardada
                    extra["Set-Cookie"] = f"nexo_modelo={m.id}; Path=/; SameSite=Lax; Max-Age=2592000"
                self._enviar_cache(cacheado("panel", D.PANEL.stat().st_mtime_ns, lambda: panel_html().encode("utf-8")),
                                   "text/html; charset=utf-8", extra=extra)
            elif ruta == "/ia/nexo_ia.js":
                self._enviar(200, JS.read_bytes(), "application/javascript; charset=utf-8")
            elif ruta == "/ia/cotizaciones.js":
                self._enviar(200, (JS.parent / "cotizaciones.js").read_bytes(), "application/javascript; charset=utf-8")
            elif ruta == "/api/presupuestos":
                self._enviar(200, {"ok": True, "versiones": bootstrap.catalogo_presupuestos().listar()})
            elif ruta == "/api/presupuestos/comparar":
                self._enviar(200, bootstrap.comparar_presupuestos((q.get("a") or ["actual"])[0],
                                                                 (q.get("b") or ["actual"])[0]))
            elif ruta == "/api/presupuestos/recursos":
                p = bootstrap.catalogo_presupuestos().leer((q.get("version_presupuesto") or ["actual"])[0])
                self._enviar(200, {"ok": True, "fuente": p["fuente"], "recursos": list(p["recursos"].values())})
            elif ruta == "/api/ping":
                self._enviar(200, {"ok": True, "version": "nexo-ia", "modelo": m.id, "version_modelo": m.version})
            elif ruta == "/api/datos":
                self._enviar_cache(cacheado("datos", D.ruta_registros().stat().st_mtime_ns, datos_actuales))
            elif ruta == "/api/geometria":
                # Misma URL para todos los modelos: se usa ETag = versión de datos. El navegador revalida y, si no
                # cambió, recibe 304 sin cuerpo (no se vuelve a bajar el 3D); si cambió de modelo, recibe el nuevo.
                etag = f'"{m.id}-{m.huellas["version_datos"]}"'
                if self.headers.get("If-None-Match") == etag:
                    self._cabeceras(304, "application/json", 0, "no-cache", {"ETag": etag})
                    self.end_headers()
                    return
                self._enviar_cache(cacheado("geo", m.huellas["version_datos"], D.geometria_bytes), cache="no-cache", extra={"ETag": etag})
            elif ruta == "/api/modelos":
                self._enviar(200, {"ok": True, "actual": m.resumen(), "modelos": D.listar()})
            elif ruta == "/api/registros.json":           # mismo formato que registros_<modelo>.json del complemento
                self._enviar(200, D.ruta_registros().read_bytes(), extra={
                    "Content-Disposition": f'attachment; filename="registros_{m.id}-{m.version}.json"'})
            elif ruta == "/api/ia/estado":
                self._enviar(200, {"ok": True, "llm": llm.descripcion(), "llm_activo": llm.disponible(),
                                   "solo_lectura": SOLO_LECTURA, "puede_escribir": self.puede_escribir(),
                                   "modelo": m.resumen(), "huellas": m.huellas, "modelos_ml": auditoria()["modelos"]})
            elif ruta == "/api/ia/auditoria":
                self._enviar(200, {"ok": True, **auditoria()})
            elif ruta == "/api/ia/escaneo":               # último escaneo procesado de este modelo
                self._enviar(200, escaneo.ultimo() or {"ok": True, "vacio": True})
            elif ruta == "/api/ia/escaneo/ifc":           # georreferencia del IFC cargado (si hay)
                self._enviar(200, ifc_modelo.georef() or {"ok": True, "vacio": True})
            elif ruta == "/api/ia/escaneo/simulada.ply":  # la última nube sintética TAL CUAL saldría de WebODM (antes de alinear)
                p = D.estado() / "nube_simulada.ply"
                if not p.exists():
                    raise LookupError("Todavía no se generó una nube sintética")
                self._enviar(200, p.read_bytes(), "application/octet-stream",
                             extra={"Content-Disposition": f'attachment; filename="{p.name}"'})
            elif ruta == "/api/ia/escaneo/nube.bin":      # nube alineada para el visor (binario compacto)
                self._enviar(200, escaneo.vista_binaria(), "application/octet-stream")
            elif ruta == "/api/ia/escaneo/nube.ply":      # la misma nube, con color, para CloudCompare / ReCap / Revit
                self._enviar(200, escaneo.vista_ply_bytes(), "application/octet-stream",
                             extra={"Content-Disposition": f'attachment; filename="nube_alineada_{m.id}.ply"'})
            elif ruta == "/api/ia/bitacora":
                self._enviar(200, {"ok": True, "eventos": bitacora.leer(min(int((q.get("n") or [200])[0]), 2000),
                                                                       (q.get("tarea") or [None])[0])})
            elif ruta == "/api/ia/escaneo/historial":
                self._enviar(200, {"ok": True, "escaneos": escaneo.historial()})
            elif ruta == "/api/ia/costos":                # costos y presupuesto (mismas fórmulas que el panel) + IA
                corte = (q.get("corte") or [None])[0]
                self._enviar(200, {"ok": True, **costos.resumen(corte[:10] if corte else None,
                                                               escaneo_ultimo=escaneo.ultimo(), auditoria=auditoria())})
            elif ruta == "/api/ia/costos/modelo":         # BIM 5D: partida por partida, cuánto sale del modelo
                self._enviar(200, {"ok": True, **costos.desde_modelo(), "cambio_version": costos.cambio_version()})
            elif ruta in ("/api/ia/simulacion/etapas", "/api/ia/simulacion/etapas.bin"):   # la obra construyéndose (solo memoria)
                corte = ((q.get("corte") or [""])[0][:10]) or None
                if not simulacion._nubes:
                    limitar(self.ip(), pesado=True)
                with candado("simulacion"):
                    meta, binario = simulacion.etapas(corte, int((q.get("semilla") or [7])[0]))
                if ruta.endswith(".bin"):
                    self._enviar(200, binario, "application/octet-stream")
                else:
                    self._enviar(200, meta)
            elif ruta == "/api/ia/export/powerbi.zip":
                self._enviar(200, exportar.zip_powerbi(auditoria()), "application/zip", extra={
                    "Content-Disposition": f'attachment; filename="nexo_powerbi_{m.id}-{m.version}.zip"'})
            elif ruta == "/api/ia/bitacora.jsonl":
                p = bitacora.ruta()
                self._enviar(200, p.read_bytes() if p.exists() else b"", "application/x-ndjson; charset=utf-8",
                             extra={"Content-Disposition": f'attachment; filename="bitacora_ia_{m.id}.jsonl"'})
            else:
                self._enviar(404, {"ok": False, "error": f"No existe GET {u.path}"})
        except Exception as ex:          # noqa: BLE001
            self._error(ex)

    # ---------------- POST
    def do_POST(self):
        u = urlparse(self.path)
        ruta, q = u.path.rstrip("/").lower(), parse_qs(u.query)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n < 0:
                raise ValueError("Longitud de petición no válida.")
            origen = self.headers.get("Origin")
            if origen and urlparse(origen).netloc != self.headers.get("Host"):
                raise PermissionError("Origen externo no permitido.")
            if ruta == "/api/admin/publicar":
                if not TOKEN_ADMIN or not hmac.compare_digest(self.headers.get("X-Nexo-Admin") or "", TOKEN_ADMIN):
                    raise PermissionError("Falta o no coincide X-Nexo-Admin (NEXO_TOKEN_ADMIN).")
                if n > MAX_ZIP:
                    raise ValueError(f"El zip supera {MAX_ZIP // 2**20} MB")
                r = publicar(self.rfile.read(n), self.headers.get("X-Nexo-Autor") or self.ip())
                D.usar(r["id"], r["version"])
                bitacora.anotar("publicar", **r)

                def precalcular(mid=r["id"], ver=r["version"]):   # ML + auditoría en segundo plano
                    try:
                        D.usar(mid, ver); auditoria()
                    except Exception as ex:  # noqa: BLE001
                        print(f"[publicar] no se pudo precalcular {mid} {ver}: {ex}")
                threading.Thread(target=precalcular, daemon=True).start()
                self._enviar(200, {"ok": True, **r, "modelos": D.listar()})
                return
            if ruta == "/api/ia/escaneo/ifc":             # cuerpo = .ifc del proyecto (coordenadas compartidas)
                self.exigir_escritura()
                if n > MAX_NUBE:
                    raise ValueError(f"El IFC supera {MAX_NUBE // 2**20} MB")
                self.elegir_modelo(q)
                with candado("escaneo"):
                    self._enviar(200, {"ok": True, **ifc_modelo.cargar(self.rfile.read(n), (q.get("nombre") or ["modelo.ifc"])[0])})
                return
            if ruta == "/api/ia/escaneo/subir":           # cuerpo = archivo de nube (.ply/.las/.laz/.xyz/.pts) tal cual
                self.exigir_escritura()
                limitar(self.ip(), pesado=True)
                if n > MAX_NUBE:
                    raise ValueError(f"La nube supera {MAX_NUBE // 2**20} MB: submuestréala (p. ej. 3-5 cm) en CloudCompare o WebODM")
                self.elegir_modelo(q)
                nombre = os.path.basename((q.get("nombre") or ["nube.ply"])[0])[:120]
                nube, rgb = nube_io.leer_con_color(self.rfile.read(n), nombre)
                with candado("escaneo"):
                    self._enviar(200, escaneo.procesar(nube, (q.get("fecha") or [None])[0], nombre, rgb=rgb))
                return
            if n > 2 * 1024 * 1024:
                raise ValueError("Petición demasiado grande")
            ped = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(ped, dict):
                raise ValueError("Se esperaba un objeto JSON.")
            self.elegir_modelo(q)
            if ruta == "/api/metrado":
                if not ped.get("simular"):
                    self.exigir_escritura()
                ped["_usuario"] = self.ip()
                self._enviar(200, registrar(ped))
            elif ruta == "/api/presupuestos/cotizar":
                self._enviar(200, bootstrap.proponer_cotizacion(ped))
            elif ruta == "/api/presupuestos/cotizar/confirmar":
                self.exigir_escritura()
                self._enviar(200, bootstrap.guardar_cotizacion(ped))
            elif ruta == "/api/ia/narrar":
                limitar(self.ip())
                self._enviar(200, {"ok": True, **narrador.narrar(hallazgo_por_id(ped["id"]), forzar=bool(ped.get("forzar")) and self.puede_escribir())})
            elif ruta == "/api/ia/decision":
                self.exigir_escritura()
                if ped.get("decision") not in ("aceptado", "descartado", "pendiente"):
                    raise ValueError("decision debe ser aceptado, descartado o pendiente")
                h = hallazgo_por_id(ped["id"])
                ev = bitacora.anotar("decision", hallazgo=h["id"], regla=h["regla"], decision=ped["decision"],
                                     motivo=(ped.get("motivo") or "")[:500], usuario=(ped.get("usuario") or "anónimo")[:80],
                                     ip=self.ip(), impacto_soles=h["impacto_soles"])
                self._enviar(200, {"ok": True, "evento": ev})
            elif ruta == "/api/ia/simulacion":           # SOLO SIMULACIÓN: no escribe nada (permitida en solo lectura)
                limitar(self.ip(), pesado=True)
                with candado("simulacion"):
                    self._enviar(200, simulacion.simular((str(ped.get("corte") or "")[:10] or None), int(ped.get("semilla", 7))))
            elif ruta == "/api/ia/escaneo/demo":         # nube sintética con verdad conocida, generada desde el modelo
                self.exigir_escritura()
                limitar(self.ip(), pesado=True)
                fecha = str(ped.get("fecha") or "2027-06-30")[:10]
                with candado("escaneo"):
                    con_ifc = bool(ped.get("desde_ifc")) and ifc_modelo.georef() is not None
                    nube, verdad, _, rgb = sintetico.generar(fecha, semilla=int(ped.get("semilla", 7)),
                                                             falsos_registrados=int(ped.get("falsos", 2)),
                                                             ruido=float(ped.get("ruido", 0.02)), huecos=float(ped.get("huecos", 0.15)),
                                                             desde_ifc=con_ifc, coords_ifc=con_ifc)
                    nube_io.escribir_ply(D.estado() / "nube_simulada.ply", nube, rgb)
                    nombre = f"sintética {fecha} desde {'el IFC, en coordenadas UTM' if con_ifc else 'el modelo del panel'} (semilla {verdad['semilla']})"
                    self._enviar(200, escaneo.procesar(nube, fecha, nombre, verdad=verdad, rgb=rgb))
            elif ruta == "/api/ia/parte":                # chat del parte diario: registra trabajos o responde de costos
                texto = str(ped.get("texto", ""))[:2000]
                if consultas.es_pregunta(texto):
                    corte = (str(ped.get("corte") or "")[:10] or None)
                    r = consultas.responder(texto, corte, escaneo.ultimo(), auditoria())
                    bitacora.anotar("consulta", texto=texto, tema=r["tema"], corte=r["corte"], usuario=self.ip())
                    self._enviar(200, {"ok": True, **r})
                else:
                    limitar(self.ip())
                    self._enviar(200, {"ok": True, "tipo": "parte", **parte_diario.procesar(texto, ped.get("fecha"))})
            else:
                self._enviar(404, {"ok": False, "error": f"No existe POST {u.path}"})
        except Exception as ex:          # noqa: BLE001
            self._error(ex)


def main():
    modelos = D.listar()
    if not modelos:
        raise SystemExit("No hay modelos. Define NEXO_REPO=/ruta/a/BIM-IA o publica uno en NEXO_MODELOS.")
    print(f"Repo (solo lectura): {D.REPO}\nModelos publicados: {D.MODELOS}\nEstado (registros, bitácora, caché): {D.ESTADO}")
    print("Preparando modelos (la primera vez entrena el ML de cada versión vigente)…")
    for mm in modelos:
        D.usar(mm["id"])
        a = auditoria()
        print(f"  · {mm['id']} {mm['vigente']} ({len(mm['versiones'])} versión/es): {len(D.elementos())} elementos, "
              f"{len(a['hallazgos'])} hallazgos, datos v.{D.huellas()['version_datos']}")
    print(f"  LLM: {llm.PROVEEDOR} · {llm.MODELO}" + ("" if llm.disponible() else "  (sin modelo: redacción por plantilla)"))

    def precalentar_escaneo():                   # puntos de referencia del modelo (≈5 s por versión)
        for mm in modelos:
            try:
                D.usar(mm["id"]); escaneo.referencia()
                if not ifc_modelo.georef() and mm["id"] == modelos[0]["id"]:     # IFC dejado en el repo: se carga solo
                    for ifc in sorted((D.REPO / "3_Modelo_y_parametros").glob("*.ifc")):
                        print(f"[escaneo] cargando georreferencia desde {ifc.name}…")
                        ifc_modelo.cargar(ifc.read_bytes(), ifc.name)
                        break
                if ifc_modelo.georef():
                    ifc_modelo.mallas_en_modelo()
            except Exception as ex:  # noqa: BLE001
                print(f"[escaneo] {mm['id']}: {ex}")
    threading.Thread(target=precalentar_escaneo, daemon=True).start()
    modo = "SOLO LECTURA" if SOLO_LECTURA else ("escritura con token" if TOKEN else "escritura abierta (modo local)")
    srv = ThreadingHTTPServer((HOST, PUERTO), Manejador)
    srv.daemon_threads = True
    print(f"Abre http://{'127.0.0.1' if HOST in ('0.0.0.0', '') else HOST}:{PUERTO}   [{modo}]")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
