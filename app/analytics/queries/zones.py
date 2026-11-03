"""SQL analitico por zona sobre los GeoParquet (ADR-0023). Funciones
sincronas: DuckDB bloquea, asi que el use case las envuelve en run_blocking.

Una zona es una provincia (la `province_code` que cada evento trae desde la
ingesta: punto dentro, poligono de mayor solape) o un circulo, resuelto con
ST_DWithin en EPSG:25830 como /v1/events/near. Las fechas son civiles en
Europe/Madrid: un dia con aviso es un dia del calendario de quien lo lee.
"""

from dataclasses import dataclass
from typing import Any

from app.analytics import engine

# El SQL se compone con f-strings (noqa S608) porque la columna de agrupacion
# y el predicado de zona cambian por llamada. Lo interpolado son SIEMPRE
# fragmentos fijos de este modulo; todo valor que llega de fuera (codigo de
# provincia, centro, radio, ano, rutas) viaja como parametro `?`.
_LOCAL = "Europe/Madrid"


@dataclass(frozen=True, slots=True)
class Circle:
    lon: float
    lat: float
    radius_m: float


def _local_date(column: str) -> str:
    return f"CAST(timezone('{_LOCAL}', {column}) AS DATE)"


def _zone_filter(province: str | None, circle: Circle | None) -> tuple[str, list[Any]]:
    """Predicado sobre el alias `e` y sus parametros. Sin zona: todo."""
    if province is not None:
        return "e.province_code = ?", [province]
    if circle is not None:
        return (
            "ST_DWithin("
            "ST_Transform(e.geom, 'EPSG:4326', 'EPSG:25830', always_xy := true), "
            "ST_Transform(ST_Point(?, ?), 'EPSG:4326', 'EPSG:25830', always_xy := true), ?)",
            [circle.lon, circle.lat, circle.radius_m],
        )
    return "TRUE", []


def warning_days(
    *,
    snapshot: str,
    year: int,
    group: str,
    province: str | None = None,
    circle: Circle | None = None,
) -> dict[Any, dict[int, int]]:
    """Dias con aviso por nivel: {clave: {severidad: dias}}.

    Cada aviso se expande a los dias civiles que cubre y cada dia cuenta una
    vez, con su peor nivel. Asi un Update que sustituye a un aviso no suma
    dias (el CAP cuenta cada Update como una fila, ADR-0010). `group` es
    'month' (clave = mes) o 'province' (clave = codigo INE, dias del ano).
    """
    key = "month(day)" if group == "month" else "province_code"
    where, params = _zone_filter(province, circle)
    sql = f"""
        WITH w AS (
            SELECT e.province_code, e.severity,
                   {_local_date("e.starts_at")} AS d0,
                   {_local_date("coalesce(e.ends_at, e.starts_at)")} AS d1
            FROM read_parquet(?) e
            WHERE e.hazard_type = 'weather_warning' AND e.severity >= 2
              AND year({_local_date("e.starts_at")}) <= ?
              AND year({_local_date("coalesce(e.ends_at, e.starts_at)")}) >= ?
              AND {where}
        ), days AS (
            SELECT province_code, severity,
                   CAST(unnest(generate_series(d0, d1, INTERVAL 1 DAY)) AS DATE) AS day
            FROM w
        ), worst AS (
            SELECT {"province_code" if group == "province" else "NULL AS province_code"},
                   day, max(severity) AS severity
            FROM days WHERE year(day) = ?
            GROUP BY ALL
        )
        SELECT {key} AS k, severity, count(*) FROM worst
        WHERE {key} IS NOT NULL
        GROUP BY 1, 2
    """  # noqa: S608
    with engine.cursor() as con:
        rows = con.execute(sql, [snapshot, year, year, *params, year]).fetchall()
    out: dict[Any, dict[int, int]] = {}
    for k, severity, days in rows:
        out.setdefault(k, {})[severity] = days
    return out


def earthquakes(
    *,
    snapshot: str,
    year: int,
    group: str,
    province: str | None = None,
    circle: Circle | None = None,
) -> dict[Any, tuple[int, float | None]]:
    """Sismos y magnitud maxima: {clave: (n, max_magnitud)}."""
    key = f"month({_local_date('e.starts_at')})" if group == "month" else "e.province_code"
    where, params = _zone_filter(province, circle)
    sql = f"""
        SELECT {key} AS k, count(*),
               max(TRY_CAST(json_extract_string(e.attrs, '$.magnitude') AS DOUBLE))
        FROM read_parquet(?) e
        WHERE e.hazard_type = 'earthquake'
          AND year({_local_date("e.starts_at")}) = ?
          AND {where}
        GROUP BY 1
        HAVING k IS NOT NULL
    """  # noqa: S608
    with engine.cursor() as con:
        rows = con.execute(sql, [snapshot, year, *params]).fetchall()
    return {k: (n, magnitude) for k, n, magnitude in rows}


def burnt_areas(
    *,
    snapshot: str,
    year: int,
    group: str,
    province: str | None = None,
    circle: Circle | None = None,
) -> dict[Any, tuple[int, float]]:
    """Areas quemadas y hectareas: {clave: (n, ha)}. Los focos no cuentan."""
    key = f"month({_local_date('e.starts_at')})" if group == "month" else "e.province_code"
    where, params = _zone_filter(province, circle)
    sql = f"""
        SELECT {key} AS k, count(*),
               coalesce(round(sum(TRY_CAST(json_extract_string(e.attrs, '$.area_ha')
                                  AS DOUBLE)), 1), 0)
        FROM read_parquet(?) e
        WHERE e.hazard_type = 'wildfire'
          AND json_extract_string(e.attrs, '$.kind') = 'burnt_area'
          AND year({_local_date("e.starts_at")}) = ?
          AND {where}
        GROUP BY 1
        HAVING k IS NOT NULL
    """  # noqa: S608
    with engine.cursor() as con:
        rows = con.execute(sql, [snapshot, year, *params]).fetchall()
    return {k: (n, hectares) for k, n, hectares in rows}


def history_since(*, snapshots: list[str]) -> Any:
    """Primer dia civil con datos de TODAS las fuentes: antes, un cero no
    significa "nada paso" sino "aun no mirabamos"."""
    if not snapshots:
        return None
    firsts = " UNION ALL ".join(
        f"SELECT min({_local_date('starts_at')}) AS d FROM read_parquet(?)"  # noqa: S608
        for _ in snapshots
    )
    with engine.cursor() as con:
        row = con.execute(f"SELECT max(d) FROM ({firsts})", snapshots).fetchone()  # noqa: S608
    return row[0] if row else None


def province_names(*, provinces: str) -> list[tuple[str, str]]:
    with engine.cursor() as con:
        rows = con.execute(
            "SELECT province_code, name FROM read_parquet(?) ORDER BY province_code",
            [provinces],
        ).fetchall()
    return [(code, name) for code, name in rows]


_LEVELS = {2: "yellow", 3: "orange", 4: "red"}


def _metrics(
    days: dict[int, int] | None,
    quakes: tuple[int, float | None] | None,
    fires: tuple[int, float] | None,
) -> dict[str, Any]:
    days = days or {}
    return {
        **{f"warning_days_{name}": days.get(sev, 0) for sev, name in _LEVELS.items()},
        "earthquakes": quakes[0] if quakes else 0,
        "max_magnitude": quakes[1] if quakes else None,
        "burnt_areas": fires[0] if fires else 0,
        "burned_area_ha": fires[1] if fires else 0.0,
    }


def zone_monthly(
    *,
    snapshots: dict[str, str],
    year: int,
    province: str | None = None,
    circle: Circle | None = None,
) -> dict[str, Any]:
    """Los doce meses de una zona (ceros incluidos) y desde cuando hay datos.

    `snapshots` solo trae las fuentes con fichero: sin snapshot, su metrica
    queda a cero.
    """

    def zone_args(source: str) -> dict[str, Any]:
        return {
            "snapshot": snapshots[source],
            "year": year,
            "group": "month",
            "province": province,
            "circle": circle,
        }

    days = warning_days(**zone_args("aemet")) if "aemet" in snapshots else {}
    quakes = earthquakes(**zone_args("ign")) if "ign" in snapshots else {}
    fires = burnt_areas(**zone_args("effis")) if "effis" in snapshots else {}
    return {
        "history_since": history_since(snapshots=list(snapshots.values())),
        "rows": [
            {"month": m, **_metrics(days.get(m), quakes.get(m), fires.get(m))} for m in range(1, 13)
        ],
    }


def provinces_summary(*, snapshots: dict[str, str], provinces: str, year: int) -> dict[str, Any]:
    """Las 52 provincias (ceros incluidos) con las metricas del ano."""
    days = (
        warning_days(snapshot=snapshots["aemet"], year=year, group="province")
        if "aemet" in snapshots
        else {}
    )
    quakes = (
        earthquakes(snapshot=snapshots["ign"], year=year, group="province")
        if "ign" in snapshots
        else {}
    )
    fires = (
        burnt_areas(snapshot=snapshots["effis"], year=year, group="province")
        if "effis" in snapshots
        else {}
    )
    return {
        "history_since": history_since(snapshots=list(snapshots.values())),
        "rows": [
            {
                "province_code": code,
                "province": name,
                **_metrics(days.get(code), quakes.get(code), fires.get(code)),
            }
            for code, name in province_names(provinces=provinces)
        ],
    }


__all__ = [
    "Circle",
    "burnt_areas",
    "earthquakes",
    "history_since",
    "province_names",
    "provinces_summary",
    "warning_days",
    "zone_monthly",
]
