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

from app.core.rate_limit import _client_ip, rate_limit_exceeded_handler


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


def _request(xff: str | None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": ("127.0.0.1", 5000)})


def test_client_ip_con_un_salto_es_el_cliente() -> None:
    assert _client_ip(_request("203.0.113.7")) == "203.0.113.7"


def test_client_ip_con_varios_saltos_toma_el_que_anadio_el_proxy() -> None:
    # Lo que el cliente mande en XFF va delante; el ultimo valor lo pone el
    # proxy de confianza. Tomar el primero permitiria rotar IPs falsas.
    assert _client_ip(_request("1.2.3.4, 198.51.100.42, 203.0.113.7")) == "203.0.113.7"


def test_client_ip_sin_cabecera_usa_la_ip_de_la_conexion() -> None:
    assert _client_ip(_request(None)) == "127.0.0.1"
