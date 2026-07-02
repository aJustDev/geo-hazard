"""Meta-test: toda columna Geometry del esquema declara SRID 4326 e indice.

El drift de SRID es silencioso y catastrofico: una columna sin SRID acepta
geometrias en cualquier sistema y las consultas espaciales devuelven basura
sin error. Este test lo convierte en fallo de CI en cuanto alguien anade una
columna geometrica olvidando el contrato.
"""

from geoalchemy2 import Geometry

import app.core.db_registry  # noqa: F401 - puebla Base.metadata
from app.core.db import Base


def test_toda_columna_geometry_declara_srid_4326_y_gist() -> None:
    geometry_columns = [
        (table.name, column.name, column.type)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, Geometry)
    ]
    assert geometry_columns, "el esquema deberia tener al menos una columna Geometry"

    for table_name, column_name, geometry_type in geometry_columns:
        where = f"{table_name}.{column_name}"
        assert geometry_type.srid == 4326, f"{where}: SRID {geometry_type.srid}, debe ser 4326"
        assert geometry_type.spatial_index, f"{where}: falta spatial_index=True (GiST)"
