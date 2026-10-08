"""Versión web de paramsx: un Flask local en 127.0.0.1 que se abre en el navegador.
Flask viene con paramsx desde la 2.4.1."""


def flask_disponible():
    try:
        import flask  # noqa: F401
    except ImportError:
        return False
    return True
