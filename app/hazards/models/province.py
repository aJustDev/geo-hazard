from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ProvinceORM(Base):
    """Provincia INE en PostGIS: geografia de referencia (ADR-0021, ADR-0023).

    Sembrada por migracion desde data/reference/provinces_es.parquet, el
    mismo fichero que lee el plano analitico (ADR-0013): una sola fuente de
    verdad. Vive en hazards porque es dato de referencia de los eventos: cada
    evento guarda su provincia (`HazardEventORM.province_code`, la calcula la
    funcion SQL `hazard_event_province` en un trigger) y de ahi tiran el
    filtro de la API y las areas de provincia de notifications.
    """

    __tablename__ = "provinces"

    # Codigo INE de dos cifras ("30" Murcia, "51" Ceuta).
    code: Mapped[str] = mapped_column(String(2), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    geom: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False
    )

    __table_args__ = (CheckConstraint("code ~ '^[0-9]{2}$'", name="codigo_ine"),)


__all__ = ["ProvinceORM"]
