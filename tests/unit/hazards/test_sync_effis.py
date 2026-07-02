from unittest.mock import AsyncMock

from app.core.effis.drivers.fake import EffisFakeClient
from app.hazards.use_cases.sync_effis import SyncEffisUseCase


def make_use_case(
    upsert_result: tuple[int, int],
) -> tuple[SyncEffisUseCase, AsyncMock, AsyncMock, AsyncMock]:
    repo = AsyncMock()
    repo.upsert_batch.return_value = upsert_result
    sync_state = AsyncMock()
    bus = AsyncMock()
    return SyncEffisUseCase(repo=repo, sync_state=sync_state, event_bus=bus), repo, sync_state, bus


async def test_con_cambios_publica_evento_de_lote() -> None:
    use_case, repo, sync_state, bus = make_use_case((2, 0))

    result = await use_case.execute(client=EffisFakeClient())

    assert result == (2, 0)
    rows = repo.upsert_batch.call_args.args[0]
    assert len(rows) == 2  # hotspot + area quemada del fake
    sync_state.record_success.assert_awaited_once_with("effis")
    bus.publish.assert_awaited_once()
    event_type, payload = bus.publish.call_args.args
    assert event_type == "hazards.batch_ingested"
    assert payload == {"source": "effis", "inserted": 2, "updated": 0}


async def test_sin_cambios_no_publica() -> None:
    # Re-servido identico: el upsert no toca nada y el snapshot no se reescribe.
    use_case, _, sync_state, bus = make_use_case((0, 0))

    await use_case.execute(client=EffisFakeClient())

    sync_state.record_success.assert_awaited_once()
    bus.publish.assert_not_awaited()


async def test_mapeo_de_filas() -> None:
    use_case, repo, _, _ = make_use_case((0, 0))

    await use_case.execute(client=EffisFakeClient())

    hotspot, burnt = repo.upsert_batch.call_args.args[0]
    assert hotspot["source"] == "effis"
    assert hotspot["hazard_type"] == "wildfire"
    assert hotspot["severity"] == 2
    assert hotspot["attrs"]["kind"] == "hotspot"
    assert hotspot["ends_at"] is None
    assert len(hotspot["content_hash"]) == 64

    assert burnt["attrs"]["kind"] == "burnt_area"
    assert burnt["attrs"]["area_ha"] == 820.0
    assert burnt["severity"] == 3  # 820 ha -> nivel 3
