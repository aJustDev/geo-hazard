from typing import Any

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import CheckConstraint, ColumnElement, String, and_, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Mapped, mapped_column

from app.core.db import Base


class ProvinceORM(Base):
    """Provincia INE en PostGIS: geografia de referencia (ADR-0021, ADR-0023).

    Sembrada por migracion desde data/reference/provinces_es.parquet, el
    mismo fichero que lee el plano analitico (ADR-0013): una sola fuente de
    verdad. Vive en hazards porque es dato de referencia de los eventos: el
    filtro por provincia de la API y las areas vigiladas de notifications la
    usan con la misma regla (`in_province`).
    """

    __tablename__ = "provinces"

    # Codigo INE de dos cifras ("30" Murcia, "51" Ceuta).
    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    geom: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False
    )

    __table_args__ = (CheckConstraint("code ~ '^[0-9]{2}$'", name="codigo_ine"),)


def in_province(
    geom: ColumnElement[Any] | InstrumentedAttribute[Any], code: ColumnElement[str] | str
) -> ColumnElement[bool]:
    """Si un evento es de la provincia `code`.

    Un punto lo es si cae dentro. Un poligono, si es la provincia con la que
    mas solapa: las zonas AEMET cruzan limites provinciales y las costeras son
    sobre todo mar, asi que ni la interseccion simple ni el centroide sirven
    (ADR-0021). El primer termino es una interseccion con la geometria de la
    provincia, que permite usar el indice GiST de `geom` como prefiltro; el
    subquery de mayor solape solo corre para los candidatos.
    """
    province_geom = select(ProvinceORM.geom).where(ProvinceORM.code == code).scalar_subquery()
    largest_overlap = (
        select(ProvinceORM.code)
        .where(func.ST_Intersects(ProvinceORM.geom, geom))
        .order_by(func.ST_Area(func.ST_Intersection(ProvinceORM.geom, geom)).desc())
        .limit(1)
        .scalar_subquery()
    )
    return and_(
        func.ST_Intersects(province_geom, geom),
        or_(func.ST_Dimension(geom) == 0, largest_overlap == code),
    )


__all__ = ["ProvinceORM", "in_province"]
