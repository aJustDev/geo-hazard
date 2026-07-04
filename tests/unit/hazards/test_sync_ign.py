from unittest.mock import AsyncMock

from app.core.ign.drivers.fake import IgnFakeClient
from app.hazards.use_cases.sync_ign import SyncIgnUseCase


def make_use_case(
    upsert_result: tuple[int, int],
) -> tuple[SyncIgnUseCase, AsyncMock, AsyncMock, AsyncMock]:
    repo = AsyncMock()
    repo.upsert_batch.return_value = upsert_result
    sync_state = AsyncMock()
    bus = AsyncMock()
    return SyncIgnUseCase(repo=repo, sync_state=sync_state, event_bus=bus), repo, sync_state, bus


async def test_con_cambios_publica_evento_de_lote() -> None:
    use_case, repo, sync_state, bus = make_use_case((2, 0))

    result = await use_case.execute(client=IgnFakeClient())

    assert result == (2, 0)
    assert len(repo.upsert_batch.call_args.args[0]) == 2
    event_type, payload = bus.publish.call_args.args
    assert event_type == "hazards.batch_ingested"
    assert payload == {"source": "ign", "inserted": 2, "updated": 0}


async def test_el_cursor_guarda_el_ultimo_evento() -> None:
    use_case, _, sync_state, _ = make_use_case((0, 0))

    await use_case.execute(client=IgnFakeClient())

    kwargs = sync_state.record_success.call_args.kwargs
    # El fake mas reciente es el sismo del Golfo de Cadiz (2026-07-02 05:06:37Z).
    assert kwargs["cursor"] == {"last_event_at": "2026-07-02T05:06:37+00:00"}


async def test_sin_cambios_no_publica() -> None:
    use_case, _, sync_state, bus = make_use_case((0, 0))

    await use_case.execute(client=IgnFakeClient())

    sync_state.record_success.assert_awaited_once()
    bus.publish.assert_not_awaited()


async def test_mapeo_de_filas() -> None:
    use_case, repo, _, _ = make_use_case((0, 0))

    await use_case.execute(client=IgnFakeClient())

    golfo, canarias = repo.upsert_batch.call_args.args[0]
    assert golfo["source"] == "ign"
    assert golfo["hazard_type"] == "earthquake"
    assert golfo["external_id"] == "fake-eq-1"
    assert golfo["severity"] == 2  # magnitud 3.5
    # Un sismo es puntual: su ventana es su propio instante (ADR-0016).
    assert golfo["ends_at"] == golfo["starts_at"]
    assert golfo["attrs"]["magnitude"] == 3.5
    assert golfo["attrs"]["region"] == "GOLFO DE CADIZ"
    assert len(golfo["content_hash"]) == 64

    assert canarias["severity"] == 1  # magnitud 2.6
