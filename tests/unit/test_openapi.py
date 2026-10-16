"""El OpenAPI publico (/docs) es la documentacion de la API para integradores:
cada ruta se describe, declara sus errores con el envelope real y los
schemas principales traen ejemplo."""

import pytest

from app.main import app

ERROR_REF = "#/components/schemas/ErrorResponse"


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def _op(spec: dict, path: str) -> dict:
    return spec["paths"][path]["get"]


def _error_ref(op: dict, status: str) -> str:
    return op["responses"][status]["content"]["application/json"]["schema"]["$ref"]


def test_metadatos_de_la_api(spec: dict) -> None:
    info = spec["info"]
    assert info["license"]["name"] == "MIT"
    assert "NOTICE" in info["description"]
    assert {t["name"] for t in spec["tags"]} >= {"Events", "Analytics", "Sources", "Health"}


def test_cada_ruta_tiene_resumen_y_descripcion(spec: dict) -> None:
    for path, item in spec["paths"].items():
        if path == "/metrics":
            continue
        op = item["get"]
        assert op.get("summary"), path
        assert op.get("description"), path


@pytest.mark.parametrize(
    ("path", "statuses"),
    [
        ("/v1/events", ["400", "422", "429"]),
        ("/v1/events/near", ["422", "429"]),
        ("/v1/events/clusters", ["400", "422", "429"]),
        ("/v1/events/{event_id}", ["404", "422", "429"]),
        ("/v1/analytics/wildfires/burned-area", ["422", "429", "503"]),
        ("/v1/analytics/earthquakes/frequency", ["422", "429", "503"]),
        ("/v1/analytics/warnings/summary", ["422", "429", "503"]),
    ],
)
def test_errores_declarados_con_el_envelope_real(
    spec: dict, path: str, statuses: list[str]
) -> None:
    op = _op(spec, path)
    for status in statuses:
        assert _error_ref(op, status) == ERROR_REF, (path, status)


def test_schemas_principales_con_ejemplo(spec: dict) -> None:
    schemas = spec["components"]["schemas"]
    for name in ["EventFeatureCollection", "SourcesStatusResponse", "ErrorResponse"]:
        assert schemas[name].get("examples"), name


def test_severidad_documentada(spec: dict) -> None:
    props = spec["components"]["schemas"]["EventProperties"]["properties"]
    assert "1" in props["severity"]["description"]
    assert "4" in props["severity"]["description"]
