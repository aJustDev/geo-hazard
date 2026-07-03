"""SQL analitico de avisos meteorologicos sobre el GeoParquet de AEMET."""

from typing import Any

from app.analytics import engine


def summary_by_phenomenon(
    *, snapshot: str, year: int, phenomenon_code: str | None
) -> list[dict[str, Any]]:
    """Avisos de un ano agrupados por fenomeno y nivel.

    El fenomeno AEMET viaja como "AT;Temperaturas maximas": el filtro opera
    sobre el codigo (la parte antes del ';'), que es estable entre idiomas.
    `zones` cuenta zonas de aviso distintas: 40 avisos sobre la misma zona
    no son lo mismo que 40 zonas afectadas.
    """
    sql = """
        SELECT json_extract_string(attrs, '$.phenomenon') AS phenomenon,
               json_extract_string(attrs, '$.level') AS level,
               count(*) AS warnings,
               count(DISTINCT json_extract_string(attrs, '$.zone')) AS zones
        FROM read_parquet(?)
        WHERE hazard_type = 'weather_warning'
          AND year(starts_at) = ?
          AND (? IS NULL
               OR split_part(json_extract_string(attrs, '$.phenomenon'), ';', 1) = ?)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    with engine.cursor() as con:
        rows = con.execute(sql, [snapshot, year, phenomenon_code, phenomenon_code]).fetchall()
    return [{"phenomenon": r[0], "level": r[1], "warnings": r[2], "zones": r[3]} for r in rows]


__all__ = ["summary_by_phenomenon"]
