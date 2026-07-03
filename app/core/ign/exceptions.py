class IgnError(Exception):
    """Base de los errores del driver IGN (infraestructura, no dominio)."""


class IgnTransientError(IgnError):
    """Timeout, 5xx o red caida: reintentable en el siguiente poll del job."""


class IgnProtocolError(IgnError):
    """Respuesta 200 pero imparseable: cambio de contrato en la fuente.

    No es transitoria: reintentarla no la arregla. Debe llegar al log como
    error para que un humano mire el driver.
    """


__all__ = ["IgnError", "IgnProtocolError", "IgnTransientError"]
