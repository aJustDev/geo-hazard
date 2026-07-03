"""SQL analitico de incendios sobre los GeoParquet. Funciones sincronas:
DuckDB bloquea, asi que el use case las envuelve en run_blocking."""

from typing import Any

from app.analytics import engine


def burned_area_by_month(
    *, snapshot: str, provinces: str, year: int, province_code: str | None
) -> list[dict[str, Any]]:
    """Hectareas quemadas por provincia y mes de un ano.

    Solo areas quemadas (kind=burnt_area): los hotspots son detecciones sin
    extension. La asignacion a provincia es por el CENTROIDE del poligono:
    un incendio que cruza el limite cuenta una sola vez, no en ambas.
    """
    sql = """
        SELECT p.province_code,
               p.name AS province,
               month(e.starts_at) AS month,
               count(*) AS events,
               round(sum(CAST(json_extract_string(e.attrs, '$.area_ha') AS DOUBLE)), 1)
                   AS burned_area_ha
        FROM read_parquet(?) e
        JOIN read_parquet(?) p ON ST_Within(ST_Centroid(e.geom), p.geom)
        WHERE e.hazard_type = 'wildfire'
          AND json_extract_string(e.attrs, '$.kind') = 'burnt_area'
          AND year(e.starts_at) = ?
          AND (? IS NULL OR p.province_code = ?)
        GROUP BY 1, 2, 3
        ORDER BY 1, 3
    """
    with engine.cursor() as con:
        rows = con.execute(
            sql, [snapshot, provinces, year, province_code, province_code]
        ).fetchall()
    return [
        {
            "province_code": r[0],
            "province": r[1],
            "month": r[2],
            "events": r[3],
            "burned_area_ha": r[4],
        }
        for r in rows
    ]


__all__ = ["burned_area_by_month"]
