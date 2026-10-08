"""Versión web de paramsx: un Flask local en 127.0.0.1 que se abre en el navegador.
Necesita el extra [web]: pip install 'paramsx[web]'."""


def flask_disponible():
    try:
        import flask  # noqa: F401
    except ImportError:
        return False
    return True
