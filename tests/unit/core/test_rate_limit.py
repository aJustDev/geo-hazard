"""Wiring del rate limiting (ADR-0017): el handler propio y el middleware.

Se monta un FastAPI minimo con un limiter HABILITADO a un limite bajo (el resto
de la suite lo tiene desactivado via tests/conftest.py) para afirmar que al
superar la cuota se responde con el envelope homogeneo {detail, code} y
Retry-After, no con el 429 por defecto de slowapi.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.core.rate_limit import rate_limit_exceeded_handler


def _app() -> FastAPI:
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["2/minute"],
        enabled=True,
        headers_enabled=True,
    )
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/ping")
    async def ping(request: Request) -> dict[str, Any]:
        return {"ok": True}

    return app


def test_supera_el_limite_devuelve_429_con_envelope_y_retry_after() -> None:
    client = TestClient(_app())

    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200

    third = client.get("/ping")
    assert third.status_code == 429
    body = third.json()
    assert body["code"] == "rate_limited"
    assert body["detail"] == "rate limit exceeded"
    assert third.headers["Retry-After"] == "60"
