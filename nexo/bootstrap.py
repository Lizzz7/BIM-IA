"""Punto de composición. La API solicita servicios aquí; no construye reglas de negocio."""
def catalogo_presupuestos():
    from nexo.modulos.proyectos.infraestructura import repositorio_archivos as datos
    from nexo.modulos.presupuestos.infraestructura.catalogo_archivos import CatalogoArchivos
    modelo = datos.actual()
    return CatalogoArchivos(modelo, datos.registro().get(modelo.id, {}))


def proponer_cotizacion(pedido):
    from nexo.modulos.presupuestos.aplicacion.casos_uso.actualizar_cotizacion import ejecutar
    return ejecutar(catalogo_presupuestos(), pedido)


def comparar_presupuestos(anterior, nueva):
    from nexo.modulos.presupuestos.aplicacion.casos_uso.comparar_versiones import ejecutar
    return ejecutar(catalogo_presupuestos(), anterior, nueva)


def guardar_cotizacion(pedido):
    from nexo.modulos.proyectos.infraestructura import repositorio_archivos as datos
    from nexo.modulos.presupuestos.infraestructura.repositorio_archivos import RevisionesJSON
    with datos.candado("cotizaciones"):
        propuesta = proponer_cotizacion(pedido)
        propuesta["modelo"] = datos.actual().resumen()
        identidad = RevisionesJSON(datos.estado() / "cotizaciones").guardar(propuesta)
    return {"ok": True, "id": identidad, "estado": "Propuesta, no aprobada",
            "aviso": "Revisión guardada; no cambia el presupuesto vigente ni las valorizaciones cerradas."}


def main():
    from nexo.api.http import main as iniciar
    iniciar()


if __name__ == "__main__":
    main()
