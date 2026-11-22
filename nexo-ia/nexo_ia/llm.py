"""Cliente de LLM con varios proveedores intercambiables y salida JSON validada.

Se elige con variables de entorno (nada de claves en el código ni en el navegador):

  NEXO_LLM=plantilla   (por defecto) sin modelo: texto por plantilla determinista. La demo nunca se cae.
  NEXO_LLM=ollama      local, sin internet.   NEXO_LLM_MODELO=granite3.3:8b  OLLAMA_HOST=http://127.0.0.1:11434
  NEXO_LLM=openai      cualquier API compatible con OpenAI (OpenAI, Groq, vLLM, LM Studio, ...).
                       OPENAI_API_KEY, OPENAI_BASE_URL (def. https://api.openai.com/v1), NEXO_LLM_MODELO
  NEXO_LLM=watsonx     IBM watsonx.ai (Granite).  WATSONX_APIKEY, WATSONX_PROJECT_ID,
                       WATSONX_URL (def. https://us-south.ml.cloud.ibm.com), NEXO_LLM_MODELO (def. ibm/granite-3-8b-instruct)
  NEXO_LLM=anthropic   ANTHROPIC_API_KEY, NEXO_LLM_MODELO

Toda llamada: temperatura 0, respuesta JSON, validación de esquema y 1 reintento con el error.
"""
import json
import os
import time
import urllib.request

PROVEEDOR = os.environ.get("NEXO_LLM", "plantilla").lower()
MODELO = os.environ.get("NEXO_LLM_MODELO", {
    "ollama": "granite3.3:8b", "openai": "gpt-4o-mini", "watsonx": "ibm/granite-3-8b-instruct",
    "anthropic": "claude-sonnet-4-5", "plantilla": "plantilla"}.get(PROVEEDOR, ""))
TIEMPO = float(os.environ.get("NEXO_LLM_TIMEOUT", "60"))


class ErrorLLM(Exception):
    pass


def disponible() -> bool:
    return PROVEEDOR != "plantilla"


def descripcion() -> dict:
    return {"proveedor": PROVEEDOR, "modelo": MODELO}


def _post(url, cuerpo, cab):
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **cab}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIEMPO) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ErrorLLM(f"{PROVEEDOR} HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}") from e
    except OSError as e:
        raise ErrorLLM(f"{PROVEEDOR}: {e}") from e


_token = {"valor": None, "vence": 0}


def _token_watsonx():
    if _token["valor"] and time.time() < _token["vence"] - 60:
        return _token["valor"]
    data = f"grant_type=urn:ibm:params:oauth:grant-type:apikey&apikey={os.environ['WATSONX_APIKEY']}".encode()
    req = urllib.request.Request("https://iam.cloud.ibm.com/identity/token", data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIEMPO) as r:
        j = json.loads(r.read())
    _token.update(valor=j["access_token"], vence=time.time() + j.get("expires_in", 3600))
    return _token["valor"]


def _chat(sistema, usuario, esquema):
    if PROVEEDOR == "ollama":
        host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        r = _post(f"{host}/api/chat", {"model": MODELO, "stream": False, "format": esquema, "options": {"temperature": 0},
                                       "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]}, {})
        return r["message"]["content"]
    if PROVEEDOR == "openai":
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        r = _post(f"{base}/chat/completions", {"model": MODELO, "temperature": 0, "response_format": {"type": "json_object"},
                                               "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]},
                  {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
        return r["choices"][0]["message"]["content"]
    if PROVEEDOR == "watsonx":
        url = os.environ.get("WATSONX_URL", "https://us-south.ml.cloud.ibm.com").rstrip("/")
        r = _post(f"{url}/ml/v1/text/chat?version=2024-10-08",
                  {"model_id": MODELO, "project_id": os.environ["WATSONX_PROJECT_ID"], "temperature": 0, "max_tokens": 900,
                   "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}]},
                  {"Authorization": f"Bearer {_token_watsonx()}", "Accept": "application/json"})
        return r["choices"][0]["message"]["content"]
    if PROVEEDOR == "anthropic":
        r = _post("https://api.anthropic.com/v1/messages",
                  {"model": MODELO, "max_tokens": 900, "temperature": 0, "system": sistema,
                   "messages": [{"role": "user", "content": usuario}]},
                  {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
        return "".join(b.get("text", "") for b in r["content"])
    raise ErrorLLM(f"Proveedor desconocido: {PROVEEDOR}")


def _extraer_json(txt):
    txt = txt.strip()
    if txt.startswith("```"):
        txt = txt.strip("`").split("\n", 1)[1] if "\n" in txt else txt
    i, j = txt.find("{"), txt.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("la respuesta no contiene un objeto JSON")
    return json.loads(txt[i:j + 1])


def validar(obj, esquema, ruta="$"):
    """Validador mínimo de JSON Schema (type, required, properties, enum, items, maxLength)."""
    t = esquema.get("type")
    tipos = {"object": dict, "array": list, "string": str, "number": (int, float), "integer": int, "boolean": bool}
    if t and not isinstance(obj, tipos[t]):
        raise ValueError(f"{ruta}: se esperaba {t}")
    if "enum" in esquema and obj not in esquema["enum"]:
        raise ValueError(f"{ruta}: '{obj}' no está entre {esquema['enum']}")
    if t == "string" and "maxLength" in esquema and len(obj) > esquema["maxLength"]:
        raise ValueError(f"{ruta}: texto de más de {esquema['maxLength']} caracteres")
    if t == "object":
        for k in esquema.get("required", []):
            if k not in obj:
                raise ValueError(f"{ruta}: falta '{k}'")
        for k, sub in esquema.get("properties", {}).items():
            if k in obj and obj[k] is not None:
                validar(obj[k], sub, f"{ruta}.{k}")
    if t == "array":
        for n, x in enumerate(obj):
            validar(x, esquema.get("items", {}), f"{ruta}[{n}]")
    return obj


def pedir_json(sistema, usuario, esquema, chequeo=None):
    """Pide un JSON que cumpla el esquema. `chequeo(obj)` puede devolver una lista de problemas
    (p. ej. números sin respaldo); si hay problemas se reintenta una vez explicándolos al modelo.
    Devuelve (obj, meta)."""
    if not disponible():
        raise ErrorLLM("sin LLM configurado (NEXO_LLM=plantilla)")
    sistema = sistema + "\n\nResponde SOLO con un objeto JSON que cumpla este esquema:\n" + json.dumps(esquema, ensure_ascii=False)
    intentos, t0, msg, ultimo = [], time.time(), usuario, None
    for intento in range(2):
        crudo = _chat(sistema, msg, esquema)
        try:
            obj = validar(_extraer_json(crudo), esquema)
            problemas = chequeo(obj) if chequeo else []
        except (ValueError, json.JSONDecodeError) as e:
            obj, problemas = None, [f"JSON inválido: {e}"]
        intentos.append({"intento": intento + 1, "crudo": crudo[:2000], "problemas": problemas})
        ultimo = obj
        if obj is not None and not problemas:
            break
        msg = usuario + "\n\nTu respuesta anterior tuvo estos problemas, corrígelos:\n- " + "\n- ".join(problemas)
    return ultimo, {**descripcion(), "ms": int((time.time() - t0) * 1000), "intentos": intentos,
                    "aceptado": ultimo is not None and not intentos[-1]["problemas"]}
