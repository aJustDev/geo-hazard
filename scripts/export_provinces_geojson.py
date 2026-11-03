"""Provincias simplificadas para el front (ADR-0022, ADR-0023).

Lee data/reference/provinces_es.parquet y escribe un FeatureCollection
GeoJSON `{code, name}` ligero para pintar provincias en el navegador: el
contorno de "mi zona" y la coropleta. No es la geometria de calculo (esa
vive en PostGIS y en el parquet): aqui manda el peso.

- Descarta las partes de menos de ~1 km2 (islotes: el 41% de los vertices),
  salvo la mayor de cada provincia (Ceuta y Melilla son pequenas).
- Simplifica cada parte a 0,005 grados (~500 m) y redondea a 4 decimales.

Simplificar provincia a provincia puede abrir rendijas de unos cientos de
metros entre vecinas; a la escala del mapa no se ven.

Uso: uv run python scripts/export_provinces_geojson.py <salida.geojson>
"""

import json
import sys
from pathlib import Path

import duckdb

SOURCE = Path(__file__).resolve().parents[1] / "data" / "reference" / "provinces_es.parquet"
TOLERANCE = 0.005
MIN_PART_DEG2 = 1e-4  # ~1 km2 a la latitud de la peninsula
PRECISION = 4


def main(target: Path) -> None:
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial")
    rows = con.execute(
        """
        WITH parts AS (
            SELECT province_code, name, unnest(ST_Dump(geom)).geom AS part
            FROM read_parquet(?)
        ), ranked AS (
            SELECT *, row_number() OVER (PARTITION BY province_code
                                         ORDER BY ST_Area(part) DESC) AS rank
            FROM parts
        )
        SELECT province_code, name,
               ST_AsGeoJSON(ST_Collect(list(ST_SimplifyPreserveTopology(part, ?))))
        FROM ranked
        WHERE rank = 1 OR ST_Area(part) >= ?
        GROUP BY 1, 2
        ORDER BY 1
        """,
        [str(SOURCE), TOLERANCE, MIN_PART_DEG2],
    ).fetchall()

    def rounded(value: object) -> object:
        if isinstance(value, float):
            return round(value, PRECISION)
        if isinstance(value, list):
            return [rounded(v) for v in value]
        return value

    features = []
    for code, name, geometry in rows:
        geom = json.loads(geometry)
        geom["coordinates"] = rounded(geom["coordinates"])
        features.append(
            {"type": "Feature", "properties": {"code": code, "name": name}, "geometry": geom}
        )
    collection = {"type": "FeatureCollection", "features": features}
    target.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")))
    print(f"{target}: {len(features)} provincias, {target.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("uso: export_provinces_geojson.py <salida.geojson>")
    main(Path(sys.argv[1]))
