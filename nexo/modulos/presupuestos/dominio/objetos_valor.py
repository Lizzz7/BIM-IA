"""Valores económicos explícitos: no aceptar NaN, booleanos o precios implícitos."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def numero(valor):
    if isinstance(valor, bool):
        raise ValueError("Un booleano no es un importe.")
    try:
        n = Decimal(str(valor))
    except (ValueError, InvalidOperation):
        raise ValueError("Importe no numérico.") from None
    if not n.is_finite() or abs(n) > Decimal("1e15"):
        raise ValueError("Importe fuera de rango.")
    return n


def moneda(valor):
    return numero(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def unidad(valor):
    return str(valor).strip().lower().replace("³", "3").replace("²", "2").replace("^", "")


@dataclass(frozen=True)
class Cotizacion:
    codigo: str
    precio: Decimal
    unidad: str
    fuente: str
    fecha: str
    incluye_igv: bool
    tasa_igv: Decimal
    moneda: str = "PEN"
    alcance: str = ""

    def __post_init__(self):
        if not self.codigo or not self.unidad or not self.fuente.strip() or not self.alcance.strip():
            raise ValueError("Código, unidad, fuente y alcance comparable son obligatorios.")
        if len(self.fuente) > 1000 or len(self.alcance) > 2000:
            raise ValueError("Fuente o alcance demasiado largos.")
        if self.moneda != "PEN":
            raise ValueError("Solo se comparan cotizaciones en PEN, sin conversión implícita.")
        if not isinstance(self.incluye_igv, bool):
            raise ValueError("Indica explícitamente si incluye IGV.")
        if numero(self.precio) < 0 or not 0 <= numero(self.tasa_igv) <= 1:
            raise ValueError("Precio o tasa de IGV fuera de rango.")
        if not isinstance(self.fecha, str) or len(self.fecha) != 10:
            raise ValueError("Fecha de cotización inválida.")
        date.fromisoformat(self.fecha)

    @property
    def precio_sin_igv(self):
        return moneda(numero(self.precio) / (1 + numero(self.tasa_igv))) if self.incluye_igv else moneda(self.precio)
