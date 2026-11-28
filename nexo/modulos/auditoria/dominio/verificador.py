"""Verificador anti-alucinación: todo número que escriba el LLM debe existir en la evidencia.

Se extraen los números del texto generado (formatos 1,232.57 · 1232,57 · 0.634 · 86 %) y se comparan con
todos los números presentes en la evidencia (valores, textos, títulos). Se aceptan:
  - el mismo valor redondeado a los decimales que se escribieron,
  - porcentajes que corresponden a una fracción de la evidencia (0.86 -> 86 %),
  - una diferencia relativa ≤ 0.5 %.
No se verifican: códigos de partida (04.05.01), fechas (2027-03-08, 08/03/2027) ni años.
"""
import re

_COD = re.compile(r"\b\d{2}(?:\.\d{2}){1,3}\b")                   # 04.05.01
_FECHA = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_NUM = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|(?<![\w.])-?\d+(?:[.,]\d+)?\s?%?")


def _a_float(s):
    s = s.replace(" ", "")
    pct = s.endswith("%")
    s = s.rstrip("%")
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")
    elif re.fullmatch(r"-?\d+,\d+", s):
        s = s.replace(",", ".")
    try:
        return float(s), pct, (len(s.split(".")[1]) if "." in s else 0)
    except ValueError:
        return None, pct, 0


def numeros(texto):
    limpio = _FECHA.sub(" ", _COD.sub(" ", texto))
    out = []
    for m in _NUM.finditer(limpio):
        v, pct, dec = _a_float(m.group(0))
        if v is not None:
            out.append((m.group(0).strip(), v, pct, dec))
    return out


def permitidos(*fuentes):
    vals = set()

    def rec(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            vals.add(float(x))
        elif isinstance(x, str):
            for _, v, _, _ in numeros(x):
                vals.add(v)
        elif isinstance(x, dict):
            for v in x.values():
                rec(v)
        elif isinstance(x, (list, tuple, set)):
            for v in x:
                rec(v)
    for f in fuentes:
        rec(f)
    return vals


def _respaldado(v, pct, dec, vals):
    cands = [v, abs(v)] + ([v / 100] if pct else [])
    for c in cands:
        for p in vals:
            for q in (p, abs(p), p * 100 if pct or abs(p) <= 1 else p):
                if round(q, dec) == round(c, dec) or (q and abs(c - q) / abs(q) <= 0.005):
                    return True
    return False


def verificar(texto, *fuentes, ignorar_menores_que=10, enteros_libres=True):
    """Devuelve {'ok', 'numeros', 'sin_respaldo'}. Los enteros pequeños (< 10) se admiten
    (conteos como «2 elementos», «1 cara»), salvo enteros_libres=False."""
    vals = permitidos(*fuentes)
    revisados, malos = [], []
    for crudo, v, pct, dec in numeros(texto):
        if enteros_libres and dec == 0 and not pct and abs(v) < ignorar_menores_que:
            continue
        ok = _respaldado(v, pct, dec, vals)
        revisados.append({"texto": crudo, "valor": v, "respaldado": ok})
        if not ok:
            malos.append(crudo)
    return {"ok": not malos, "numeros": revisados, "sin_respaldo": malos}
