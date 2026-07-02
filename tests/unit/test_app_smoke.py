import httpx

from app.main import app


async def test_liveness_ok() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v1/health/liveness")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


async def test_openapi_exposes_health_routes() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/v1/health/liveness" in paths
    assert "/v1/health/readiness" in paths
