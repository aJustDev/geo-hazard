from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app import main as main_module
from app.core import startup


async def test_lifespan_sin_db_no_arranca_workers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con la BD caida la app arranca degradada: ready=False y workers parados.

    El readiness respondera 503 pero liveness sigue vivo; los workers solo
    arrancan con BD disponible para no entrar en bucles de reconexion inutiles.
    """
    monkeypatch.setattr(startup.settings, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(main_module, "check_database", AsyncMock(return_value="UNAVAILABLE"))

    app = main_module.app
    async with app.router.lifespan_context(app):
        assert app.state.ready is False
        assert app.state.job_worker._task is None
        assert app.state.outbox_worker._task is None

    assert app.state.ready is False
