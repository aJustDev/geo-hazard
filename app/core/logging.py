"""Logging estructurado con request-id (ADR-0019).

Un contextvar propaga el request-id desde el middleware hasta cualquier log de
la peticion sin tocar cada llamada a logging. `RequestIdFilter` lo vuelca en el
LogRecord para que el formatter JSON lo emita; `log_config.json` es la fuente
unica de verdad del formato (app + access logs de uvicorn).
"""

import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

# "-" como default para los logs emitidos fuera de una peticion (arranque,
# workers): el campo request_id siempre existe y el formatter nunca falla.
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """Inyecta record.request_id en cada LogRecord del handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware mas externo: fija el request-id (entrante o generado) antes de
    cualquier otra capa y lo devuelve en la cabecera de respuesta, envolviendo
    tambien 429 y errores.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = _request_id.set(rid)
        try:
            response = await call_next(request)
        finally:
            _request_id.reset(token)
        response.headers[REQUEST_ID_HEADER] = rid
        return response
