from typing import Protocol


class CatalogoPresupuestos(Protocol):
    def listar(self) -> list: ...
    def leer(self, identificador: str) -> dict: ...


class RepositorioRevisiones(Protocol):
    def guardar(self, propuesta: dict) -> str: ...
