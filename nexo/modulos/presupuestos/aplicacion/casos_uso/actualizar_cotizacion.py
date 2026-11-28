from nexo.modulos.presupuestos.dominio.objetos_valor import Cotizacion, numero
from nexo.modulos.presupuestos.dominio.reglas import cotizar
from nexo.modulos.presupuestos.aplicacion.puertos import CatalogoPresupuestos


def ejecutar(catalogo: CatalogoPresupuestos, pedido):
    if not isinstance(pedido, dict):
        raise ValueError("Cotización no válida.")
    c = Cotizacion(codigo=pedido.get("codigo", ""), precio=numero(pedido.get("precio")),
                   unidad=pedido.get("unidad", ""), fuente=pedido.get("fuente", ""),
                   fecha=pedido.get("fecha", ""), incluye_igv=pedido.get("incluye_igv"),
                   tasa_igv=numero(pedido.get("tasa_igv")), moneda=pedido.get("moneda", "PEN"),
                   alcance=pedido.get("alcance", ""))
    base = catalogo.leer(pedido.get("version", "actual"))
    if pedido.get("base_sha256") and pedido["base_sha256"] != base["fuente"].get("sha256"):
        raise ValueError("El presupuesto cambió desde la vista previa. Vuelve a calcular la propuesta.")
    return cotizar(base, c)
