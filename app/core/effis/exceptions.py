class EffisError(Exception):
    """Base de los errores del driver EFFIS (infraestructura, no dominio)."""


class EffisTransientError(EffisError):
    """Timeout, 5xx o backend caido: reintentable en el siguiente poll del job."""


class EffisProtocolError(EffisError):
    """Respuesta 200 pero imparseable: cambio de contrato en la fuente.

    No es transitoria: reintentarla no la arregla. Debe llegar al log como
    error para que un humano mire el driver.
    """


__all__ = ["EffisError", "EffisProtocolError", "EffisTransientError"]
