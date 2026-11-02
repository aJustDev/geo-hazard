from typing import Any

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import CheckConstraint, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampsMixin, UUIDPkMixin

AREA_KINDS = ("province", "bbox", "circle")


class WatchAreaORM(UUIDPkMixin, TimestampsMixin, Base):
    """Area vigilada: lo que se pidio y la geometria a la que se resuelve.

    La geometria se materializa al crearla (ADR-0021). En bbox y circulo un
    evento casa si la toca; en provincia, un punto si cae dentro y un
    poligono si esa es la provincia con la que mas solapa.
    """

    __tablename__ = "watch_areas"

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    # Entradas tal cual se pidieron: {"code"}, {"bbox"} o {"lon","lat","radius_m"}.
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    geom: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint("kind IN ('province', 'bbox', 'circle')", name="kind_conocido"),
    )
