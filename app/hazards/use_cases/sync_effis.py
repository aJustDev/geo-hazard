import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.effis.driver import EffisClient
from app.core.effis.types import KIND_HOTSPOT, EffisRecord
from app.core.events.bus import EventBus
from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.repos.sync_state import SourceSyncStateRepo
from app.hazards.services.content_hash import content_hash
from app.hazards.services.geometry import geojson_to_wkb
from app.hazards.services.severity import effis_severity

logger = logging.getLogger(__name__)

SOURCE = "effis"
BATCH_INGESTED = "hazards.batch_ingested"


@dataclass(slots=True)
class SyncEffisUseCase:
    """Reconcilia el catalogo EFFIS contra hazard_events.

    Ciclo de vida (ADR-0016): un hotspot es una deteccion puntual (ventana =
    su instante); un area quemada queda ABIERTA (ends_at NULL) mientras la
    capa NRT la sirva y se cierra cuando desaparece de ella - EFFIS no
    publica la extincion, y dejar de servir el incendio es su senal mas
    honesta. Mismo patron de cursor que los boletines AEMET (ADR-0010);
    si la fuente re-sirve un incendio cerrado, el upsert lo reabre.

    No commitea: la frontera de transaccion es del job handler que lo invoca.
    Emite hazards.batch_ingested SOLO si hubo cambios reales (el snapshot
    GeoParquet es el producto derivado del lote; un lote vacio no lo merece).
    """

    repo: HazardEventRepo
    sync_state: SourceSyncStateRepo
    event_bus: EventBus

    async def execute(self, *, client: EffisClient) -> tuple[int, int, int]:
        hotspots = await client.fetch_hotspots()
        burnt_areas = await client.fetch_burnt_areas()
        rows = [self._to_row(record) for record in hotspots + burnt_areas]

        inserted, updated = await self.repo.upsert_batch(rows)
        closed = await self._close_vanished(burnt_areas)
        await self.sync_state.record_success(
            SOURCE, cursor={"burnt_area_ids": sorted(r.external_id for r in burnt_areas)}
        )

        if inserted or updated or closed:
            await self.event_bus.publish(
                BATCH_INGESTED,
                {"source": SOURCE, "inserted": inserted, "updated": updated, "closed": closed},
            )
        logger.info(
            "effis sync: %d inserted, %d updated, %d closed (%d fetched)",
            inserted,
            updated,
            closed,
            len(rows),
        )
        return (inserted, updated, closed)

    async def _close_vanished(self, burnt_areas: list[EffisRecord]) -> int:
        # Un area quemada del cursor anterior que ya no viene en la capa NRT
        # se cierra a "ahora": la fuente dejo de observarla (ADR-0016).
        state = await self.sync_state.get(SOURCE)
        previous = set(state.cursor.get("burnt_area_ids", [])) if state is not None else set()
        vanished = previous - {r.external_id for r in burnt_areas}
        if not vanished:
            return 0
        return await self.repo.close_events(
            source=SOURCE, external_ids=vanished, ended_at=datetime.now(UTC)
        )

    @staticmethod
    def _to_row(record: EffisRecord) -> dict[str, Any]:
        attrs = {**record.attrs, "kind": record.kind}
        if record.area_ha is not None:
            attrs["area_ha"] = record.area_ha
        return {
            "source": SOURCE,
            "hazard_type": "wildfire",
            "external_id": record.external_id,
            "geom": geojson_to_wkb(record.geometry),
            "severity": effis_severity(kind=record.kind, area_ha=record.area_ha),
            "starts_at": record.observed_at,
            # Deteccion puntual = instante; area quemada = abierta hasta que
            # la capa NRT deje de servirla (la cierra _close_vanished).
            "ends_at": record.observed_at if record.kind == KIND_HOTSPOT else None,
            "attrs": attrs,
            # El hash cubre lo que define "cambio real": geometria (un area
            # quemada crece), atributos y timestamp de observacion.
            "content_hash": content_hash(
                {
                    "geometry": record.geometry,
                    "attrs": attrs,
                    "observed_at": record.observed_at.isoformat(),
                }
            ),
        }


__all__ = ["BATCH_INGESTED", "SOURCE", "SyncEffisUseCase"]
