from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.aemet.drivers.fake import AemetFakeClient
from app.core.aemet.types import MSG_TYPE_CANCEL, MSG_TYPE_UPDATE, AemetWarning
from app.hazards.use_cases.sync_aemet import SyncAemetUseCase

SENT = datetime(2026, 7, 2, 16, 28, 3, tzinfo=UTC)


def make_use_case(
    upsert_result: tuple[int, int] = (0, 0),
    *,
    previous_identifiers: list[str] | None = None,
) -> tuple[SyncAemetUseCase, AsyncMock, AsyncMock, AsyncMock]:
    repo = AsyncMock()
    repo.upsert_batch.return_value = upsert_result
    repo.close_events.return_value = 0
    sync_state = AsyncMock()
    if previous_identifiers is None:
        sync_state.get.return_value = None
    else:
        sync_state.get.return_value = SimpleNamespace(cursor={"identifiers": previous_identifiers})
    bus = AsyncMock()
    use_case = SyncAemetUseCase(repo=repo, sync_state=sync_state, event_bus=bus)
    return use_case, repo, sync_state, bus


def _naranja(external_id: str = "aviso-naranja-1", **overrides) -> AemetWarning:
    defaults = dict(
        external_id=external_id,
        msg_type="Alert",
        sent=SENT,
        event="Aviso de temperaturas maximas de nivel naranja",
        phenomenon="AT;Temperaturas maximas",
        level="naranja",
        onset=datetime(2026, 7, 3, 11, 0, 0, tzinfo=UTC),
        expires=datetime(2026, 7, 3, 18, 59, 59, tzinfo=UTC),
        polygon="39.14,-5.58 39.19,-5.61 39.21,-5.56 39.14,-5.58",
        zone="700602",
        area_desc="La Siberia extremena",
    )
    return AemetWarning(**{**defaults, **overrides})


async def test_verde_no_se_ingiere() -> None:
    # El fake trae un naranja y un verde: solo el naranja acaba en filas.
    use_case, repo, sync_state, _ = make_use_case((1, 0))

    await use_case.execute(client=AemetFakeClient())

    rows = repo.upsert_batch.call_args.args[0]
    assert [row["external_id"] for row in rows] == ["fake-aemet-naranja-1"]
    # Y el cursor tampoco lo recuerda: solo identifica lo ingerido.
    cursor = sync_state.record_success.call_args.kwargs["cursor"]
    assert cursor == {"identifiers": ["fake-aemet-naranja-1"]}


async def test_mapeo_de_filas() -> None:
    use_case, repo, _, _ = make_use_case((1, 0))

    await use_case.execute(client=AemetFakeClient(warnings=[_naranja()]))

    (row,) = repo.upsert_batch.call_args.args[0]
    assert row["source"] == "aemet"
    assert row["hazard_type"] == "weather_warning"
    assert row["severity"] == 3  # naranja
    assert row["starts_at"] == datetime(2026, 7, 3, 11, 0, 0, tzinfo=UTC)
    assert row["ends_at"] == datetime(2026, 7, 3, 18, 59, 59, tzinfo=UTC)
    assert row["attrs"]["level"] == "naranja"
    assert row["attrs"]["zone"] == "700602"
    assert len(row["content_hash"]) == 64


async def test_update_cierra_lo_que_referencia() -> None:
    update = _naranja(
        external_id="aviso-naranja-2",
        msg_type=MSG_TYPE_UPDATE,
        references=("aviso-naranja-1",),
    )
    use_case, repo, _, _ = make_use_case((1, 0))

    await use_case.execute(client=AemetFakeClient(warnings=[update]))

    # El Update se ingiere como aviso nuevo Y cierra al que supersede.
    rows = repo.upsert_batch.call_args.args[0]
    assert [row["external_id"] for row in rows] == ["aviso-naranja-2"]
    kwargs = repo.close_events.call_args.kwargs
    assert kwargs["source"] == "aemet"
    assert set(kwargs["external_ids"]) == {"aviso-naranja-1"}
    assert kwargs["ended_at"] == SENT


async def test_cancel_solo_cierra() -> None:
    cancel = AemetWarning(
        external_id="cancel-1",
        msg_type=MSG_TYPE_CANCEL,
        sent=SENT,
        references=("aviso-naranja-1",),
    )
    use_case, repo, _, bus = make_use_case((0, 0))
    repo.close_events.return_value = 1

    await use_case.execute(client=AemetFakeClient(warnings=[cancel]))

    assert repo.upsert_batch.call_args.args[0] == []
    assert set(repo.close_events.call_args.kwargs["external_ids"]) == {"aviso-naranja-1"}
    # Cerrar avisos tambien refresca el snapshot: hay evento de lote.
    payload = bus.publish.call_args.args[1]
    assert payload == {"source": "aemet", "inserted": 0, "updated": 0, "closed": 1}


async def test_desaparecido_del_boletin_se_cierra_a_ahora() -> None:
    # "aviso-retirado" estaba en el cursor anterior pero ya no viene en el
    # boletin ni tiene Cancel: AEMET lo retiro al elaborar el nuevo.
    use_case, repo, _, _ = make_use_case(
        (1, 0), previous_identifiers=["aviso-retirado", "aviso-naranja-1"]
    )

    before = datetime.now(UTC)
    await use_case.execute(client=AemetFakeClient(warnings=[_naranja()]))

    kwargs = repo.close_events.call_args.kwargs
    assert set(kwargs["external_ids"]) == {"aviso-retirado"}
    assert kwargs["ended_at"] >= before


async def test_sin_cambios_no_publica() -> None:
    use_case, _, sync_state, bus = make_use_case((0, 0))

    await use_case.execute(client=AemetFakeClient(warnings=[_naranja()]))

    sync_state.record_success.assert_awaited_once()
    bus.publish.assert_not_awaited()
