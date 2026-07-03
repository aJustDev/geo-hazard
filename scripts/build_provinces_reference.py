"""Construye data/reference/provinces_es.parquet desde el CNIG (ADR-0013).

Fuente: lineas_limite_gml.zip del servicio ATOM INSPIRE del CNIG (URL
estable, sin sesion). El fichero au_AdministrativeUnit_3rdOrder0.gml trae
las 52 provincias + Ceuta y Melilla + "territorios no asociados" (codigo
54, islotes: se excluye por no ser una provincia).

El parquet resultante se COMMITEA (~550 KB): es una referencia estatica que
cambia con anos de diferencia, y el join espacial de analytics no debe
depender de una descarga de 66 MB en cada entorno. Este script existe para
poder regenerarla de forma auditable.

Uso: uv run python scripts/build_provinces_reference.py
"""

import os
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import duckdb

SOURCE_URL = (
    "https://centrodedescargas.cnig.es/CentroDescargas/documentos/atom/au/lineas_limite_gml.zip"
)
GML_MEMBER = "au_AdministrativeUnit_3rdOrder0.gml"
TARGET = Path(__file__).resolve().parents[1] / "data" / "reference" / "provinces_es.parquet"

# ~200 m en estas latitudes: suficiente para asignar eventos a provincia sin
# arrastrar los 66 MB de geometria oficial.
SIMPLIFY_TOLERANCE_DEG = 0.002

# El GDAL embebido en duckdb-spatial busca las CA en la ruta de RedHat; en
# Debian/Ubuntu el bundle vive en otro sitio.
_DEBIAN_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


def main() -> int:
    if os.path.exists(_DEBIAN_CA_BUNDLE):
        os.environ.setdefault("CURL_CA_BUNDLE", _DEBIAN_CA_BUNDLE)

    if not SOURCE_URL.startswith("https://"):
        raise ValueError("SOURCE_URL must be https")

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "lineas_limite_gml.zip"
        print(f"downloading {SOURCE_URL} ...")
        urllib.request.urlretrieve(SOURCE_URL, archive)  # noqa: S310 - https constante
        with zipfile.ZipFile(archive) as bundle:
            bundle.extract(GML_MEMBER, tmp)
        gml = str(Path(tmp) / GML_MEMBER)

        con = duckdb.connect()
        con.execute("INSTALL spatial; LOAD spatial")
        # nationalCode INSPIRE: 34 + CCAA(2) + provincia INE(2) + ceros.
        # El GML llega etiquetado EPSG:4258 (ETRS89, ~identico a WGS84); se
        # transforma a OGC:CRS84 (no-op geometrica, always_xy conserva el
        # orden lon/lat) para que el CRS de los metadatos GeoParquet coincida
        # con el de los snapshots y DuckDB acepte el join espacial.
        # COPY no admite parametros preparados: rutas inlined (son locales).
        gml_sql = gml.replace("'", "''")
        target_sql = str(TARGET).replace("'", "''")
        con.execute(
            f"""
            COPY (
              SELECT substr(CAST(nationalCode AS VARCHAR), 5, 2) AS province_code,
                     text AS name,
                     ST_Transform(
                       ST_MakeValid(
                         ST_SimplifyPreserveTopology(geometry, {SIMPLIFY_TOLERANCE_DEG})
                       ),
                       'EPSG:4258', 'OGC:CRS84', always_xy := true
                     ) AS geom
              FROM ST_Read('{gml_sql}')
              WHERE substr(CAST(nationalCode AS VARCHAR), 5, 2) != '54'
              ORDER BY province_code
            ) TO '{target_sql}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """  # noqa: S608 - rutas locales del propio script, sin input externo
        )
        count = con.execute("SELECT count(*) FROM read_parquet(?)", [str(TARGET)]).fetchone()
        con.close()

    size_kb = TARGET.stat().st_size // 1024
    print(f"wrote {TARGET} ({count[0] if count else '?'} provinces, {size_kb} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
