"""Punto de composición. Conserva las variables de entorno y el arranque histórico."""
def main():
    from nexo.api.http import main as iniciar
    iniciar()


if __name__ == "__main__":
    main()
