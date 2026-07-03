"""SQL analitico de sismos sobre el GeoParquet del IGN."""

from typing import Any

from app.analytics import engine


def frequency_by_month(
    *, snapshot: str, year: int, min_magnitude: float | None
) -> list[dict[str, Any]]:
    """Histograma mensual de sismos de un ano, con la magnitud maxima."""
    sql = """
        SELECT month(starts_at) AS month,
               count(*) AS events,
               max(CAST(json_extract_string(attrs, '$.magnitude') AS DOUBLE)) AS max_magnitude
        FROM read_parquet(?)
        WHERE hazard_type = 'earthquake'
          AND year(starts_at) = ?
          AND CAST(json_extract_string(attrs, '$.magnitude') AS DOUBLE) >= coalesce(?, 0.0)
        GROUP BY 1
        ORDER BY 1
    """
    with engine.cursor() as con:
        rows = con.execute(sql, [snapshot, year, min_magnitude]).fetchall()
    return [{"month": r[0], "events": r[1], "max_magnitude": r[2]} for r in rows]


__all__ = ["frequency_by_month"]
