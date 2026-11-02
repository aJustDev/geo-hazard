"""Validacion de areas vigiladas (ADR-0021). Servicio puro.

Tres formas: provincia INE, rectangulo lon/lat y circulo (centro + radio).
La geometria la resuelve el repo en PostGIS; aqui solo se valida lo pedido.
"""

import math
import re
from dataclasses import dataclass

from app.hazards.services.geometry import parse_bbox

MIN_RADIUS_M = 1_000
MAX_RADIUS_M = 200_000
_PROVINCE_CODE = re.compile(r"^[0-9]{2}$")


@dataclass(frozen=True, slots=True)
class ProvinceArea:
    code: str


@dataclass(frozen=True, slots=True)
class BboxArea:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    @property
    def label(self) -> str:
        return f"rectangulo {self.min_lon},{self.min_lat},{self.max_lon},{self.max_lat}"


@dataclass(frozen=True, slots=True)
class CircleArea:
    lon: float
    lat: float
    radius_m: int

    @property
    def label(self) -> str:
        return f"{self.radius_m / 1000:g} km alrededor de {self.lat},{self.lon}"


AreaSpec = ProvinceArea | BboxArea | CircleArea


def province_area(code: str) -> ProvinceArea:
    if not _PROVINCE_CODE.match(code):
        raise ValueError("province code must be two INE digits, e.g. '30'")
    return ProvinceArea(code=code)


def bbox_area(raw: str) -> BboxArea:
    """'minLon,minLat,maxLon,maxLat', mismas reglas que el filtro bbox de la API."""
    bbox = parse_bbox(raw)
    if bbox is None:  # parse_bbox solo devuelve None si recibe None
        raise ValueError("bbox is required")
    return BboxArea(*bbox)


def circle_area(raw: str) -> CircleArea:
    """'lon,lat,km': centro en grados WGS84 y radio en kilometros."""
    parts = raw.split(",")
    if len(parts) != 3:
        raise ValueError("circle must be 'lon,lat,km'")
    lon, lat, km = (float(p) for p in parts)
    if not (math.isfinite(lon) and -180 <= lon <= 180 and math.isfinite(lat) and -90 <= lat <= 90):
        raise ValueError("circle center must be a valid WGS84 lon,lat")
    radius_m = round(km * 1000) if math.isfinite(km) else -1
    if not MIN_RADIUS_M <= radius_m <= MAX_RADIUS_M:
        raise ValueError(
            f"circle radius must be between {MIN_RADIUS_M // 1000} and {MAX_RADIUS_M // 1000} km"
        )
    return CircleArea(lon=lon, lat=lat, radius_m=radius_m)


__all__ = [
    "MAX_RADIUS_M",
    "MIN_RADIUS_M",
    "AreaSpec",
    "BboxArea",
    "CircleArea",
    "ProvinceArea",
    "bbox_area",
    "circle_area",
    "province_area",
]
