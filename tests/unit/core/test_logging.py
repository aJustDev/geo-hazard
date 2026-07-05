"""Logging estructurado con request-id (ADR-0019): el middleware fija/propaga
el id y lo devuelve en la cabecera; el filtro y el formatter emiten request_id
en el JSON; log_config.json es estructuralmente valido."""

import importlib
import json
import logging
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from app.core.logging import (
    REQUEST_ID_HEADER,
    RequestIdFilter,
    RequestIdMiddleware,
    get_request_id,
)

LOG_CONFIG = Path(__file__).resolve().parents[3] / "log_config.json"


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/echo")
    async def echo() -> dict[str, str]:
        return {"rid": get_request_id()}

    return app


def _resolve(path: str) -> Any:
    module, _, name = path.rpartition(".")
    return getattr(importlib.import_module(module), name)


async def test_genera_y_devuelve_request_id() -> None:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/echo")

    assert response.status_code == 200
    rid = response.headers[REQUEST_ID_HEADER]
    assert rid
    # El id de la cabecera es el que vio el endpoint: propagacion por contextvar.
    assert response.json()["rid"] == rid


async def test_respeta_request_id_entrante() -> None:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/echo", headers={REQUEST_ID_HEADER: "abc123"})

    assert response.headers[REQUEST_ID_HEADER] == "abc123"
    assert response.json()["rid"] == "abc123"


def test_filter_inyecta_request_id_default() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "hola", None, None)
    assert RequestIdFilter().filter(record) is True
    # Fuera de una peticion, el contextvar vale el default "-".
    assert record.request_id == "-"


def test_formatter_emite_request_id_y_renombra_campos() -> None:
    spec = dict(json.loads(LOG_CONFIG.read_text())["formatters"]["json"])
    formatter_cls = _resolve(spec.pop("()"))
    # dictConfig mapea 'format' al primer posicional (fmt) del formatter.
    fmt = spec.pop("format")
    formatter = formatter_cls(fmt, **spec)

    record = logging.LogRecord("app.x", logging.WARNING, __file__, 1, "boom", None, None)
    RequestIdFilter().filter(record)
    out = json.loads(formatter.format(record))

    assert out["request_id"] == "-"
    assert out["level"] == "WARNING"
    assert out["logger"] == "app.x"
    assert out["message"] == "boom"
    assert "timestamp" in out


def test_log_config_referencia_clases_validas() -> None:
    config = json.loads(LOG_CONFIG.read_text())
    # Las factorias referenciadas existen (un typo en el path rompe el arranque).
    assert _resolve(config["filters"]["request_id"]["()"]) is RequestIdFilter
    assert _resolve(config["handlers"]["default"]["class"]) is logging.StreamHandler
    assert config["handlers"]["default"]["formatter"] == "json"
    assert "request_id" in config["handlers"]["default"]["filters"]
