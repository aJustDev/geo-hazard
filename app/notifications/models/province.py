from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ProvinceORM(Base):
    """Provincia INE en PostGIS: referencia de las areas vigiladas (ADR-0021).

    Sembrada por migracion desde data/reference/provinces_es.parquet, el
    mismo fichero que lee el plano analitico (ADR-0013): una sola fuente de
    verdad para los dos planos. `inner_geom` es la provincia encogida 1 km,
    contra la que se casan los poligonos (un aviso AEMET que solo roza el
    borde no avisa a la vecina); se calcula una vez en la migracion.
    """

    __tablename__ = "provinces"

    # Codigo INE de dos cifras ("30" Murcia, "51" Ceuta).
    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    geom: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False
    )
    inner_geom: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False
    )

    __table_args__ = (CheckConstraint("code ~ '^[0-9]{2}$'", name="codigo_ine"),)
