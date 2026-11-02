from geoalchemy2 import Geography, Geometry
from sqlalchemy import cast, func

from app.core.exceptions.exceptions import NotFoundError
from app.core.repo import BaseRepo
from app.hazards.services.geometry import SRID_WGS84
from app.notifications.models import ProvinceORM, WatchAreaORM
from app.notifications.services.areas import BboxArea, CircleArea, ProvinceArea


class WatchAreaRepo(BaseRepo[WatchAreaORM]):
    """Crea areas vigiladas con su geometria ya resuelta (ADR-0021)."""

    model = WatchAreaORM

    async def create_province(
        self, spec: ProvinceArea, *, label: str | None = None
    ) -> WatchAreaORM:
        province = await self.session.get(ProvinceORM, spec.code)
        if province is None:
            raise NotFoundError("province", spec.code)
        return await self.create(
            WatchAreaORM(
                kind="province",
                params={"code": spec.code},
                label=label or province.name,
                geom=province.geom,
            )
        )

    async def create_bbox(self, spec: BboxArea, *, label: str | None = None) -> WatchAreaORM:
        envelope = func.ST_Multi(
            func.ST_MakeEnvelope(spec.min_lon, spec.min_lat, spec.max_lon, spec.max_lat, SRID_WGS84)
        )
        return await self.create(
            WatchAreaORM(
                kind="bbox",
                params={"bbox": [spec.min_lon, spec.min_lat, spec.max_lon, spec.max_lat]},
                label=label or spec.label,
                geom=envelope,
            )
        )

    async def create_circle(self, spec: CircleArea, *, label: str | None = None) -> WatchAreaORM:
        # Buffer geography: el radio es exacto en metros tambien en Canarias,
        # donde la proyeccion 25830 de las consultas near distorsiona.
        center = cast(
            func.ST_SetSRID(func.ST_MakePoint(spec.lon, spec.lat), SRID_WGS84),
            Geography(srid=SRID_WGS84),
        )
        disc = func.ST_Multi(
            cast(func.ST_Buffer(center, spec.radius_m, "quad_segs=16"), Geometry(srid=SRID_WGS84))
        )
        return await self.create(
            WatchAreaORM(
                kind="circle",
                params={"lon": spec.lon, "lat": spec.lat, "radius_m": spec.radius_m},
                label=label or spec.label,
                geom=disc,
            )
        )


__all__ = ["WatchAreaRepo"]
