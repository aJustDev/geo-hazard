import httpx
from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError

from app.core.exceptions.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceOverloadedError,
)
from app.core.exceptions.handlers import register_exception_handlers


def make_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/not-found")
    async def _not_found() -> None:
        raise NotFoundError("Widget", 42)

    @app.get("/conflict")
    async def _conflict() -> None:
        raise ConflictError("ya existe")

    @app.get("/overloaded")
    async def _overloaded() -> None:
        raise ServiceOverloadedError("busy", retry_after=1)

    @app.get("/integrity")
    async def _integrity() -> None:
        raise IntegrityError("INSERT ...", {}, Exception("duplicate key"))

    @app.get("/typed")
    async def _typed(n: int) -> dict:
        return {"n": n}

    return app


def make_client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_domain_exception_mapea_status_y_code() -> None:
    async with make_client(make_app()) as client:
        response = await client.get("/not-found")
    assert response.status_code == 404
    assert response.json() == {"detail": "Widget not found (id: 42)", "code": "not_found"}


async def test_conflict_usa_mensaje_libre() -> None:
    async with make_client(make_app()) as client:
        response = await client.get("/conflict")
    assert response.status_code == 409
    assert response.json() == {"detail": "ya existe", "code": "conflict"}


async def test_validation_error_422_con_detalle() -> None:
    async with make_client(make_app()) as client:
        response = await client.get("/typed", params={"n": "no-numero"})
    body = response.json()
    assert response.status_code == 422
    assert body["code"] == "validation_error"
    assert body["errors"]


async def test_integrity_error_es_409() -> None:
    async with make_client(make_app()) as client:
        response = await client.get("/integrity")
    assert response.status_code == 409
    assert response.json()["code"] == "integrity_conflict"


async def test_service_overloaded_es_503_con_retry_after() -> None:
    async with make_client(make_app()) as client:
        response = await client.get("/overloaded")
    assert response.status_code == 503
    assert response.json() == {"detail": "busy", "code": "service_overloaded"}
    assert response.headers["Retry-After"] == "1"
