"""Rate limiting por IP con slowapi (ADR-0017).

La API es publica y sin auth por diseno (dato abierto); el limite acota el
coste por cliente sin cerrar el acceso. El limiter es un singleton compartido:
lo consume el middleware para el limite global y los decoradores
`@limiter.limit(EXPENSIVE_LIMIT)` de los endpoints de computo caro. Los
contadores viven en memoria (instancia unica) y se resetean en redeploy.
"""

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings


def _client_ip(request: Request) -> str:
    # Detras de Caddy (unico ingress; la app solo escucha en 127.0.0.1) la IP
    # real del cliente viaja en X-Forwarded-For y su primer salto es el cliente;
    # confiar en ese header es seguro porque nada mas puede alcanzar la app.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=_client_ip,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
    enabled=settings.RATE_LIMIT_ENABLED,
    headers_enabled=True,
)

# Cuota estricta de los endpoints de computo (aplicada por decorador; el
# decorador reemplaza el limite global en esas rutas).
EXPENSIVE_LIMIT = settings.RATE_LIMIT_EXPENSIVE


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    # Envelope homogeneo {detail, code} en vez del handler por defecto de
    # slowapi. Retry-After 60s: todas las cuotas son por minuto, asi que ese
    # es el techo de espera honesto para reintentar.
    #
    # SINCRONO a proposito: SlowAPIMiddleware evalua el limite global por la
    # via sincrona y, si el handler fuese async, caeria a su handler por
    # defecto (perdiendo este envelope). Un handler sync sirve a ambas vias
    # (middleware global y decorador de endpoint).
    return JSONResponse(
        status_code=429,
        content={"detail": "rate limit exceeded", "code": "rate_limited"},
        headers={"Retry-After": "60"},
    )


__all__ = ["EXPENSIVE_LIMIT", "limiter", "rate_limit_exceeded_handler"]
