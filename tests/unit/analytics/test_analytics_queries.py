"""Consultas DuckDB del plano analitico contra GeoParquet reales.

Los snapshots de prueba se escriben con el MISMO writer que produccion
(_write_snapshot del handler de export): si el contrato de columnas entre
planos se rompe, estos tests lo pillan. La referencia de provincias es la
commiteada en data/reference.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import shapely

from app.analytics.paths import PROVINCES_PARQUET
from app.analytics.queries.earthquakes import frequency_by_month
from app.analytics.queries.warnings import summary_by_phenomenon
from app.analytics.queries.wildfires import burned_area_by_month
from app.hazards.event_handlers.export_geoparquet import _write_snapshot

# Centroides dentro de provincias conocidas.
BADAJOZ_POLY = shapely.box(-5.20, 39.10, -5.10, 39.20)  # La Siberia extremena
CACERES_POLY = shapely.box(-6.40, 39.44, -6.34, 39.50)  # junto a Caceres capital


def _row(
    external_id: str,
    *,
    geom: shapely.Geometry,
    hazard_type: str = "wildfire",
    source: str = "effis",
    severity: int = 2,
    starts_at: datetime,
    attrs: dict,
) -> dict:
    return {
        "id": external_id,
        "source": source,
        "hazard_type": hazard_type,
        "external_id": external_id,
        "severity": severity,
        "starts_at": starts_at,
        "ends_at": None,
        "wkb": shapely.to_wkb(geom),
        "attrs": json.dumps(attrs),
    }


def _wildfire_snapshot(tmp_path: Path) -> str:
    rows = [
        _row(
            "ba-badajoz-julio",
            geom=BADAJOZ_POLY,
            starts_at=datetime(2026, 7, 10, tzinfo=UTC),
            attrs={"kind": "burnt_area", "area_ha": 820.0},
        ),
        _row(
            "ba-badajoz-agosto",
            geom=BADAJOZ_POLY,
            starts_at=datetime(2026, 8, 2, tzinfo=UTC),
            attrs={"kind": "burnt_area", "area_ha": 100.0},
        ),
        _row(
            "ba-caceres-julio",
            geom=CACERES_POLY,
            starts_at=datetime(2026, 7, 20, tzinfo=UTC),
            attrs={"kind": "burnt_area", "area_ha": 50.5},
        ),
        # Un hotspot no aporta hectareas: debe quedar fuera.
        _row(
            "hs-fuera",
            geom=shapely.Point(-5.15, 39.15),
            starts_at=datetime(2026, 7, 10, tzinfo=UTC),
            attrs={"kind": "hotspot"},
        ),
        # Otro ano: fuera del filtro.
        _row(
            "ba-otro-ano",
            geom=BADAJOZ_POLY,
            starts_at=datetime(2025, 7, 10, tzinfo=UTC),
            attrs={"kind": "burnt_area", "area_ha": 999.0},
        ),
    ]
    path = tmp_path / "hazard_events_effis.parquet"
    _write_snapshot(rows, path)
    return str(path)


def test_area_quemada_por_provincia_y_mes(tmp_path: Path) -> None:
    snapshot = _wildfire_snapshot(tmp_path)

    rows = burned_area_by_month(
        snapshot=snapshot, provinces=str(PROVINCES_PARQUET), year=2026, province_code=None
    )

    assert [(r["province"], r["month"], r["burned_area_ha"], r["events"]) for r in rows] == [
        ("Badajoz", 7, 820.0, 1),
        ("Badajoz", 8, 100.0, 1),
        ("C\u00e1ceres", 7, 50.5, 1),
    ]


def test_area_quemada_filtra_por_provincia(tmp_path: Path) -> None:
    snapshot = _wildfire_snapshot(tmp_path)

    rows = burned_area_by_month(
        snapshot=snapshot, provinces=str(PROVINCES_PARQUET), year=2026, province_code="10"
    )

    assert len(rows) == 1
    assert rows[0]["province_code"] == "10"
    assert rows[0]["province"] == "C\u00e1ceres"


def test_frecuencia_de_sismos(tmp_path: Path) -> None:
    rows_in = [
        _row(
            f"eq-{i}",
            geom=shapely.Point(lon, lat),
            hazard_type="earthquake",
            source="ign",
            starts_at=datetime(2026, month, 5, tzinfo=UTC),
            attrs={"magnitude": magnitude, "region": "TEST"},
        )
        for i, (month, magnitude, lon, lat) in enumerate(
            [(1, 2.5, -8.0, 36.6), (1, 4.2, -9.5, 36.2), (3, 3.1, -1.7, 43.1)]
        )
    ]
    path = tmp_path / "hazard_events_ign.parquet"
    _write_snapshot(rows_in, path)

    todos = frequency_by_month(snapshot=str(path), year=2026, min_magnitude=None)
    assert todos == [
        {"month": 1, "events": 2, "max_magnitude": 4.2},
        {"month": 3, "events": 1, "max_magnitude": 3.1},
    ]

    fuertes = frequency_by_month(snapshot=str(path), year=2026, min_magnitude=3.0)
    assert fuertes == [
        {"month": 1, "events": 1, "max_magnitude": 4.2},
        {"month": 3, "events": 1, "max_magnitude": 3.1},
    ]


def test_resumen_de_avisos(tmp_path: Path) -> None:
    zona = shapely.box(-5.6, 39.0, -5.3, 39.3)
    rows_in = [
        _row(
            f"aviso-{i}",
            geom=zona,
            hazard_type="weather_warning",
            source="aemet",
            severity=severity,
            starts_at=datetime(2026, 7, day, tzinfo=UTC),
            attrs={"phenomenon": phenomenon, "level": level, "zone": zone},
        )
        for i, (phenomenon, level, severity, zone, day) in enumerate(
            [
                ("AT;Temperaturas m\u00e1ximas", "naranja", 3, "700602", 1),
                ("AT;Temperaturas m\u00e1ximas", "naranja", 3, "700603", 2),
                ("AT;Temperaturas m\u00e1ximas", "amarillo", 2, "700602", 3),
                ("VI;Viento", "amarillo", 2, "770101", 4),
            ]
        )
    ]
    path = tmp_path / "hazard_events_aemet.parquet"
    _write_snapshot(rows_in, path)

    todos = summary_by_phenomenon(snapshot=str(path), year=2026, phenomenon_code=None)
    assert todos == [
        {
            "phenomenon": "AT;Temperaturas m\u00e1ximas",
            "level": "amarillo",
            "warnings": 1,
            "zones": 1,
        },
        {
            "phenomenon": "AT;Temperaturas m\u00e1ximas",
            "level": "naranja",
            "warnings": 2,
            "zones": 2,
        },
        {"phenomenon": "VI;Viento", "level": "amarillo", "warnings": 1, "zones": 1},
    ]

    solo_calor = summary_by_phenomenon(snapshot=str(path), year=2026, phenomenon_code="AT")
    assert len(solo_calor) == 2
    assert all(r["phenomenon"].startswith("AT;") for r in solo_calor)
