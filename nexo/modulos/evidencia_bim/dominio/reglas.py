"""Políticas independientes del motor geométrico: observación no equivale a aprobación."""
from datetime import date


def validar_fecha(fecha):
    if not isinstance(fecha, str) or len(fecha) != 10:
        raise ValueError("Fecha de escaneo no válida (AAAA-MM-DD).")
    date.fromisoformat(fecha)
    return fecha


def puede_proponer(alineacion):
    # Un motor que declara explícitamente mala alineación no habilita cantidades.
    return alineacion.get("confiable") is not False


def partidas_observables(partidas):
    """La geometría exterior solo respalda propuesta de concreto, no acero oculto."""
    return [p for p in partidas if p.get("clase") == "concreto"]
