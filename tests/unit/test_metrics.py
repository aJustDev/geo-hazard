"""Endpoint /metrics (ADR-0019): expone metricas Prometheus a nivel de app,
fuera del prefijo /v1. Privado en produccion (Caddy lo bloquea al exterior)."""

import httpx

from app.main import app


async def test_metrics_expone_formato_prometheus() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Trafico previo para que exista al menos una serie de la app.
        await client.get("/v1/health/liveness")
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "starlette_requests_total" in response.text


async def test_metrics_agrupa_por_plantilla_y_descarta_rutas_inexistentes() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # UUID invalido: 422 de validacion, sin tocar la BD.
        await client.get("/v1/events/no-es-un-uuid")
        await client.get("/ruta-que-no-existe")
        response = await client.get("/metrics")

    assert 'path="/v1/events/{event_id}"' in response.text
    assert "no-es-un-uuid" not in response.text
    assert "ruta-que-no-existe" not in response.text
