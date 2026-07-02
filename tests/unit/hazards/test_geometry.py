import pytest
from geoalchemy2.shape import to_shape

from app.hazards.services.geometry import geojson_to_wkb, validate_bbox, wkb_to_geojson


def test_roundtrip_point() -> None:
    geometry = {"type": "Point", "coordinates": [-3.7, 40.4]}
    assert wkb_to_geojson(geojson_to_wkb(geometry)) == geometry


def test_roundtrip_polygon() -> None:
    geometry = {
        "type": "Polygon",
        "coordinates": [[[-5.2, 39.1], [-5.1, 39.1], [-5.1, 39.2], [-5.2, 39.1]]],
    }
    result = wkb_to_geojson(geojson_to_wkb(geometry))
    assert result["type"] == "Polygon"
    assert result["coordinates"][0][0] == [-5.2, 39.1]


def test_orden_de_ejes_es_lon_lat() -> None:
    # El punto de Madrid: lon -3.7, lat 40.4. Si alguien invierte los ejes,
    # este test lo pilla (40.4 de longitud seria un punto en otro continente).
    shape = to_shape(geojson_to_wkb({"type": "Point", "coordinates": [-3.7, 40.4]}))
    assert shape.x == -3.7
    assert shape.y == 40.4


def test_geometria_vacia_rechazada() -> None:
    with pytest.raises(ValueError, match="empty"):
        geojson_to_wkb({"type": "Polygon", "coordinates": []})


def test_validate_bbox_ok() -> None:
    assert validate_bbox(min_lon=-9.5, min_lat=36.0, max_lon=3.4, max_lat=43.8) == (
        -9.5,
        36.0,
        3.4,
        43.8,
    )


@pytest.mark.parametrize(
    ("min_lon", "min_lat", "max_lon", "max_lat"),
    [
        (3.4, 36.0, -9.5, 43.8),  # min > max en lon
        (-9.5, 43.8, 3.4, 36.0),  # min > max en lat
        (-181.0, 36.0, 3.4, 43.8),  # fuera de rango
        (-9.5, 36.0, 3.4, 91.0),  # fuera de rango
    ],
)
def test_validate_bbox_invalida(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> None:
    with pytest.raises(ValueError, match="bbox"):
        validate_bbox(min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat)
