import logging
from dataclasses import dataclass
from typing import Any

from app.core.effis.driver import EffisClient
from app.core.effis.types import EffisRecord
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

    No commitea: la frontera de transaccion es del job handler que lo invoca.
    Emite hazards.batch_ingested SOLO si hubo cambios reales (el snapshot
    GeoParquet es el producto derivado del lote; un lote vacio no lo merece).
    """

    repo: HazardEventRepo
    sync_state: SourceSyncStateRepo
    event_bus: EventBus

    async def execute(self, *, client: EffisClient) -> tuple[int, int]:
        records = await client.fetch_hotspots() + await client.fetch_burnt_areas()
        rows = [self._to_row(record) for record in records]

        inserted, updated = await self.repo.upsert_batch(rows)
        await self.sync_state.record_success(SOURCE)

        if inserted or updated:
            await self.event_bus.publish(
                BATCH_INGESTED,
                {"source": SOURCE, "inserted": inserted, "updated": updated},
            )
        logger.info(
            "effis sync: %d inserted, %d updated (%d fetched)", inserted, updated, len(rows)
        )
        return (inserted, updated)

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
            "ends_at": None,
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
