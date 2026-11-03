"""Analitica por zona (ADR-0023) sobre snapshots reales escritos con el
_write_snapshot del export: dias con aviso por su peor nivel, fechas civiles
de Madrid, provincia por `province_code` y circulo en metros."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
import shapely

from app.analytics.paths import PROVINCES_PARQUET
from app.analytics.queries.zones import Circle, provinces_summary, zone_monthly
from app.analytics.use_cases.zones import ZoneMonthlyUseCase
from app.core.exceptions.exceptions import BusinessValidationError
from app.hazards.event_handlers.export_geoparquet import _write_snapshot

VEGA = shapely.box(-1.3, 38.0, -1.0, 38.2)  # Murcia
ALMERIA = shapely.box(-2.6, 36.9, -2.3, 37.1)
MURCIA_CITY = shapely.Point(-1.13, 37.98)
CARTAGENA = shapely.Point(-0.99, 37.62)
ALMERIA_CITY = shapely.Point(-2.46, 36.84)


def _row(
    external_id: str,
    *,
    source: str,
    hazard_type: str,
    geom: shapely.Geometry,
    starts_at: datetime,
    ends_at: datetime | None = None,
    severity: int = 2,
    province_code: str | None,
    attrs: dict | None = None,
) -> dict:
    return {
        "id": external_id,
        "source": source,
        "hazard_type": hazard_type,
        "external_id": external_id,
        "severity": severity,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "wkb": shapely.to_wkb(geom),
        "attrs": json.dumps(attrs or {}),
        "province_code": province_code,
    }


def _warning(name: str, start: datetime, end: datetime, severity: int, code: str = "30") -> dict:
    return _row(
        name,
        source="aemet",
        hazard_type="weather_warning",
        geom=VEGA if code == "30" else ALMERIA,
        starts_at=start,
        ends_at=end,
        severity=severity,
        province_code=code,
    )


def _quake(name: str, point: shapely.Point, code: str | None, magnitude: float) -> dict:
    return _row(
        name,
        source="ign",
        hazard_type="earthquake",
        geom=point,
        starts_at=datetime(2026, 8, 5, 10, tzinfo=UTC),
        province_code=code,
        attrs={"magnitude": magnitude},
    )


@pytest.fixture
def snapshots(tmp_path: Path) -> dict[str, str]:
    files = {
        "aemet": [
            # Naranja dos dias (10 y 11) y amarillo el 11: el 11 cuenta naranja.
            _warning(
                "n", datetime(2026, 8, 10, 8, tzinfo=UTC), datetime(2026, 8, 11, 20, tzinfo=UTC), 3
            ),
            _warning(
                "a", datetime(2026, 8, 11, 6, tzinfo=UTC), datetime(2026, 8, 11, 12, tzinfo=UTC), 2
            ),
            # Un Update del mismo aviso (otra fila CAP) no suma dias.
            _warning(
                "a-upd",
                datetime(2026, 8, 11, 7, tzinfo=UTC),
                datetime(2026, 8, 11, 12, tzinfo=UTC),
                2,
            ),
            # 23:30 UTC del 20 es el 21 en Madrid.
            _warning(
                "tarde",
                datetime(2026, 8, 20, 23, 30, tzinfo=UTC),
                datetime(2026, 8, 20, 23, 50, tzinfo=UTC),
                2,
            ),
            # Rojo en septiembre.
            _warning(
                "r", datetime(2026, 9, 2, 9, tzinfo=UTC), datetime(2026, 9, 2, 18, tzinfo=UTC), 4
            ),
            # Otra provincia.
            _warning(
                "almeria",
                datetime(2026, 8, 10, 8, tzinfo=UTC),
                datetime(2026, 8, 10, 20, tzinfo=UTC),
                3,
                "04",
            ),
        ],
        "ign": [
            _quake("q1", MURCIA_CITY, "30", 3.1),
            _quake("q2", CARTAGENA, "30", 4.2),
            _quake("q3", ALMERIA_CITY, "04", 2.5),
        ],
        "effis": [
            _row(
                "ba",
                source="effis",
                hazard_type="wildfire",
                geom=VEGA,
                starts_at=datetime(2026, 7, 19, tzinfo=UTC),
                province_code="30",
                attrs={"kind": "burnt_area", "area_ha": "120.5"},
            ),
            _row(
                "hs",
                source="effis",
                hazard_type="wildfire",
                geom=MURCIA_CITY,
                starts_at=datetime(2026, 7, 19, tzinfo=UTC),
                province_code="30",
                attrs={"kind": "hotspot"},
            ),
        ],
    }
    out = {}
    for source, rows in files.items():
        path = tmp_path / f"hazard_events_{source}.parquet"
        _write_snapshot(rows, path)
        out[source] = str(path)
    return out


def _month(result: dict, month: int) -> dict:
    return next(row for row in result["rows"] if row["month"] == month)


def test_dias_con_aviso_por_su_peor_nivel(snapshots: dict[str, str]) -> None:
    result = zone_monthly(snapshots=snapshots, year=2026, province="30")
    august = _month(result, 8)

    assert len(result["rows"]) == 12
    assert august["warning_days_orange"] == 2  # 10 y 11
    assert august["warning_days_yellow"] == 1  # el 21 (hora de Madrid)
    assert august["warning_days_red"] == 0
    assert _month(result, 9)["warning_days_red"] == 1
    assert _month(result, 1)["warning_days_yellow"] == 0


def test_sismos_y_areas_quemadas_de_la_provincia(snapshots: dict[str, str]) -> None:
    result = zone_monthly(snapshots=snapshots, year=2026, province="30")

    assert _month(result, 8)["earthquakes"] == 2
    assert _month(result, 8)["max_magnitude"] == 4.2
    assert _month(result, 7)["burnt_areas"] == 1  # el foco no cuenta
    assert _month(result, 7)["burned_area_ha"] == 120.5
    assert _month(result, 6)["max_magnitude"] is None


def test_circulo_en_metros(snapshots: dict[str, str]) -> None:
    # 10 km alrededor de Murcia capital: entra su sismo, no el de Cartagena (~40 km).
    result = zone_monthly(
        snapshots=snapshots, year=2026, circle=Circle(lon=-1.13, lat=37.98, radius_m=10_000)
    )

    assert _month(result, 8)["earthquakes"] == 1
    assert _month(result, 8)["max_magnitude"] == 3.1


def test_desde_cuando_hay_datos_de_todas_las_fuentes(snapshots: dict[str, str]) -> None:
    result = zone_monthly(snapshots=snapshots, year=2026, province="30")

    # La fuente que empieza mas tarde manda: AEMET el 10 de agosto (IGN el 5,
    # EFFIS el 19 de julio).
    assert result["history_since"] == date(2026, 8, 10)


def test_resumen_por_provincia_con_las_52(snapshots: dict[str, str]) -> None:
    result = provinces_summary(snapshots=snapshots, provinces=str(PROVINCES_PARQUET), year=2026)
    rows = {row["province_code"]: row for row in result["rows"]}

    assert len(rows) == 52
    assert rows["30"]["warning_days_orange"] == 2
    assert rows["30"]["warning_days_red"] == 1
    assert rows["30"]["earthquakes"] == 2
    assert rows["04"]["warning_days_orange"] == 1
    assert rows["04"]["earthquakes"] == 1
    assert rows["15"]["warning_days_yellow"] == 0
    assert rows["30"]["province"]


def test_sin_snapshots_todo_a_cero() -> None:
    result = zone_monthly(snapshots={}, year=2026, province="30")

    assert result["history_since"] is None
    assert all(row["earthquakes"] == 0 for row in result["rows"])


@pytest.mark.parametrize(
    "zone",
    [
        {"province": None, "lon": None, "lat": None, "radius_m": None},
        {"province": "30", "lon": -1.0, "lat": 38.0, "radius_m": 1000.0},
        {"province": None, "lon": -1.0, "lat": 38.0, "radius_m": None},
    ],
)
async def test_exactamente_una_zona(zone: dict) -> None:
    with pytest.raises(BusinessValidationError):
        await ZoneMonthlyUseCase().execute(year=2026, **zone)
