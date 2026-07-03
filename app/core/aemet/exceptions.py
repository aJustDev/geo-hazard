class AemetError(Exception):
    """Base de los errores del driver AEMET (infraestructura, no dominio)."""


class AemetTransientError(AemetError):
    """Timeout, 5xx, cuota agotada o URL temporal caducada: reintentable."""


class AemetProtocolError(AemetError):
    """Respuesta imparseable o API key rechazada: cambio de contrato/config.

    No es transitoria: reintentarla no la arregla. Debe llegar al log como
    error para que un humano mire el driver o la key.
    """


__all__ = ["AemetError", "AemetProtocolError", "AemetTransientError"]
