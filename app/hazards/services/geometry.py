"""Servicio puro de conversion geometrica (WGS84 / PostGIS).

Sin side-effects, sin IO. Centraliza el orden de ejes: shapely, GeoJSON y
PostGIS guardan (lon, lat), pero las personas dicen (lat, lon) y CAP (AEMET)
publica sus poligonos en (lat, lon). Toda conversion entre coordenadas y
geometrias WKB pasa por aqui para que el swap sea imposible de equivocar
fuera de este modulo.
"""

from typing import Any

from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point, mapping, shape

SRID_WGS84 = 4326


def point_to_wkb(*, latitude: float, longitude: float) -> WKBElement:
    return from_shape(Point(longitude, latitude), srid=SRID_WGS84)


def geojson_to_wkb(geometry: dict[str, Any]) -> WKBElement:
    """Mapping GeoJSON (coordenadas lon, lat) -> WKB.

    Acepta cualquier tipo (Point, Polygon, MultiPolygon...): la columna
    `geom` es GEOMETRY generica a proposito (ADR-0004).
    """
    geom = shape(geometry)
    if geom.is_empty:
        raise ValueError("empty geometry")
    return from_shape(geom, srid=SRID_WGS84)


def wkb_to_geojson(element: WKBElement) -> dict[str, Any]:
    # mapping() devuelve tuplas en 'coordinates'; las normalizamos a listas
    # para un JSON/Pydantic limpio.
    geometry: dict[str, Any] = dict(mapping(to_shape(element)))
    geometry["coordinates"] = _to_lists(geometry["coordinates"])
    return geometry


def validate_bbox(
    *, min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> tuple[float, float, float, float]:
    """Valida rangos WGS84 y orden min < max. Devuelve la tupla lista para SQL."""
    if not (-180 <= min_lon < max_lon <= 180):
        raise ValueError("bbox longitudes must satisfy -180 <= min < max <= 180")
    if not (-90 <= min_lat < max_lat <= 90):
        raise ValueError("bbox latitudes must satisfy -90 <= min < max <= 90")
    return (min_lon, min_lat, max_lon, max_lat)


def _to_lists(coordinates: Any) -> Any:
    if isinstance(coordinates, list | tuple):
        return [_to_lists(item) for item in coordinates]
    return coordinates


__all__ = [
    "SRID_WGS84",
    "geojson_to_wkb",
    "point_to_wkb",
    "validate_bbox",
    "wkb_to_geojson",
]
