import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import startup
from app.core.startup import check_data_dir, check_database, check_utc_timezone


def test_check_data_dir_crea_exports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "data"
    monkeypatch.setattr(startup.settings, "DATA_DIR", str(target))

    check_data_dir()

    assert (target / "exports").is_dir()
    assert not (target / "exports" / ".write-probe").exists()


def test_check_data_dir_no_escribible_aborta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Un fichero como padre hace fallar el mkdir: simula un volumen mal montado.
    blocker = tmp_path / "fichero"
    blocker.write_text("")
    monkeypatch.setattr(startup.settings, "DATA_DIR", str(blocker / "data"))

    with pytest.raises(RuntimeError, match="not writable"):
        check_data_dir()


def test_check_utc_no_utc_en_prod_aborta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "tzname", ("CET", "CEST"))
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(startup.settings, "ENVIRONMENT", "prod")

    with pytest.raises(RuntimeError, match="not UTC"):
        check_utc_timezone()


def test_check_utc_no_utc_en_local_solo_avisa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "tzname", ("CET", "CEST"))
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(startup.settings, "ENVIRONMENT", "local")

    check_utc_timezone()  # no debe lanzar


def test_check_utc_con_tz_utc_pasa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "tzname", ("UTC", "UTC"))
    check_utc_timezone()


async def test_check_database_ok() -> None:
    engine = MagicMock()
    engine.connect.return_value = AsyncMock()

    assert await check_database(engine) == "OK"


async def test_check_database_caida() -> None:
    engine = MagicMock()
    engine.connect.side_effect = ConnectionError("boom")

    assert await check_database(engine) == "UNAVAILABLE"
