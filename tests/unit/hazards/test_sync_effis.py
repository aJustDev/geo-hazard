from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.effis.drivers.fake import EffisFakeClient
from app.hazards.use_cases.sync_effis import SyncEffisUseCase


def make_use_case(
    upsert_result: tuple[int, int],
) -> tuple[SyncEffisUseCase, AsyncMock, AsyncMock, AsyncMock]:
    repo = AsyncMock()
    repo.upsert_batch.return_value = upsert_result
    repo.close_events.return_value = 0
    sync_state = AsyncMock()
    sync_state.get.return_value = None  # sin cursor previo salvo que el test lo ponga
    bus = AsyncMock()
    return SyncEffisUseCase(repo=repo, sync_state=sync_state, event_bus=bus), repo, sync_state, bus


async def test_con_cambios_publica_evento_de_lote() -> None:
    use_case, repo, sync_state, bus = make_use_case((2, 0))

    result = await use_case.execute(client=EffisFakeClient())

    assert result == (2, 0, 0)
    rows = repo.upsert_batch.call_args.args[0]
    assert len(rows) == 2  # hotspot + area quemada del fake
    sync_state.record_success.assert_awaited_once_with(
        "effis", cursor={"burnt_area_ids": ["fake-ba-1"]}
    )
    bus.publish.assert_awaited_once()
    event_type, payload = bus.publish.call_args.args
    assert event_type == "hazards.batch_ingested"
    assert payload == {"source": "effis", "inserted": 2, "updated": 0, "closed": 0}


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
    # Deteccion puntual: ventana = instante. El area quemada queda abierta
    # hasta que la capa NRT deje de servirla (ADR-0016).
    assert hotspot["ends_at"] == hotspot["starts_at"]
    assert burnt["ends_at"] is None
    assert len(hotspot["content_hash"]) == 64

    assert burnt["attrs"]["kind"] == "burnt_area"
    assert burnt["attrs"]["area_ha"] == 820.0
    assert burnt["severity"] == 3  # 820 ha -> nivel 3


async def test_area_quemada_desaparecida_se_cierra() -> None:
    # El cursor anterior servia dos incendios; la capa NRT ya solo trae
    # fake-ba-1 -> el otro se cierra y el cierre cuenta para el evento.
    use_case, repo, sync_state, bus = make_use_case((0, 0))
    state = SimpleNamespace(cursor={"burnt_area_ids": ["fake-ba-1", "ba-viejo"]})
    sync_state.get.return_value = state
    repo.close_events.return_value = 1

    result = await use_case.execute(client=EffisFakeClient())

    assert result == (0, 0, 1)
    kwargs = repo.close_events.call_args.kwargs
    assert kwargs["source"] == "effis"
    assert kwargs["external_ids"] == {"ba-viejo"}
    bus.publish.assert_awaited_once()
    payload = bus.publish.call_args.args[1]
    assert payload == {"source": "effis", "inserted": 0, "updated": 0, "closed": 1}
