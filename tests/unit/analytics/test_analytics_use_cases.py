"""Contrato de los use cases analiticos: sin snapshot, respuesta vacia."""

from pathlib import Path

import pytest

from app.analytics.use_cases.burned_area import BurnedAreaUseCase
from app.analytics.use_cases.earthquake_frequency import EarthquakeFrequencyUseCase
from app.analytics.use_cases.warnings_summary import WarningsSummaryUseCase
from app.core import config


@pytest.fixture
def empty_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config.settings, "DATA_DIR", str(tmp_path))
    (tmp_path / "exports").mkdir()
    return tmp_path


async def test_sin_snapshot_effis_respuesta_vacia(empty_data_dir: Path) -> None:
    # Ninguna ingesta todavia no es un error: la respuesta es "nada".
    response = await BurnedAreaUseCase().execute(year=2026, province_code=None)
    assert response.year == 2026
    assert response.rows == []


async def test_sin_snapshot_ign_respuesta_vacia(empty_data_dir: Path) -> None:
    response = await EarthquakeFrequencyUseCase().execute(year=2026, min_magnitude=3.0)
    assert response.min_magnitude == 3.0
    assert response.rows == []


async def test_sin_snapshot_aemet_respuesta_vacia(empty_data_dir: Path) -> None:
    response = await WarningsSummaryUseCase().execute(year=2026, phenomenon_code="AT")
    assert response.rows == []
