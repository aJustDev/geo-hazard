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
from shapely.geometry import Point, Polygon, mapping, shape
from shapely.validation import make_valid

SRID_WGS84 = 4326
# ETRS89 / UTM huso 30N: el CRS metrico de las operaciones espaciales
# (radios, areas, clustering). Nunca se almacena: se proyecta el PARAMETRO
# al vuelo dentro de la consulta (ADR-0005).
SRID_ETRS89_UTM30 = 25830


def point_to_wkb(*, latitude: float, longitude: float) -> WKBElement:
    return from_shape(Point(longitude, latitude), srid=SRID_WGS84)


def cap_polygon_to_wkb(polygon: str) -> WKBElement:
    """Poligono CAP de AEMET ("lat,lon lat,lon ...") -> WKB.

    CAP publica cada vertice en (lat, lon), el orden INVERSO a GeoJSON/WKB;
    el swap ocurre solo aqui, como manda la doctrina del modulo.
    """
    points: list[tuple[float, float]] = []
    for pair in polygon.split():
        lat_text, _, lon_text = pair.partition(",")
        if not lon_text:
            raise ValueError(f"malformed CAP polygon vertex: {pair!r}")
        points.append((float(lon_text), float(lat_text)))
    if len(points) < 4:
        raise ValueError("CAP polygon needs at least 4 vertices (closed ring)")
    geom = Polygon(points)
    if not geom.is_valid:
        # Las zonas de aviso estan digitalizadas a mano; un anillo que se
        # auto-toca se repara en vez de descartar el aviso entero.
        geom = make_valid(geom)
    if geom.is_empty:
        raise ValueError("CAP polygon repaired to an empty geometry")
    return from_shape(geom, srid=SRID_WGS84)


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


def parse_bbox(bbox_raw: str | None) -> tuple[float, float, float, float] | None:
    """'minLon,minLat,maxLon,maxLat' -> tupla validada, o None si es None.

    Lanza ValueError si el formato o los rangos estan mal; quien llama decide
    como mapearlo (los use cases lo convierten en BusinessValidationError/400).
    """
    if bbox_raw is None:
        return None
    parts = bbox_raw.split(",")
    if len(parts) != 4:
        raise ValueError("bbox must be 'minLon,minLat,maxLon,maxLat'")
    min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
    return validate_bbox(min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat)


def _to_lists(coordinates: Any) -> Any:
    if isinstance(coordinates, list | tuple):
        return [_to_lists(item) for item in coordinates]
    return coordinates


__all__ = [
    "SRID_ETRS89_UTM30",
    "SRID_WGS84",
    "cap_polygon_to_wkb",
    "geojson_to_wkb",
    "parse_bbox",
    "point_to_wkb",
    "validate_bbox",
    "wkb_to_geojson",
]
