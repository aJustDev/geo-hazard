import logging
from dataclasses import dataclass
from typing import Any

from app.core.events.bus import EventBus
from app.core.ign.driver import IgnClient
from app.core.ign.types import IgnRecord
from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.repos.sync_state import SourceSyncStateRepo
from app.hazards.services.content_hash import content_hash
from app.hazards.services.geometry import point_to_wkb
from app.hazards.services.severity import ign_severity
from app.hazards.use_cases.sync_effis import BATCH_INGESTED

logger = logging.getLogger(__name__)

SOURCE = "ign"


@dataclass(slots=True)
class SyncIgnUseCase:
    """Reconcilia la ventana de 10 dias del catalogo sismico IGN.

    El feed re-sirve la ventana completa en cada poll y el IGN revisa sus
    analisis en continuo: magnitud y epicentro pueden cambiar dias despues
    del evento. El content_hash convierte cada revision en un update y cada
    re-servido identico en un no-op (ADR-0008). No commitea: la frontera de
    transaccion es del job handler que lo invoca.
    """

    repo: HazardEventRepo
    sync_state: SourceSyncStateRepo
    event_bus: EventBus

    async def execute(self, *, client: IgnClient) -> tuple[int, int]:
        records = await client.fetch_earthquakes()
        rows = [self._to_row(record) for record in records]

        inserted, updated = await self.repo.upsert_batch(rows)
        cursor = None
        if records:
            cursor = {"last_event_at": max(r.occurred_at for r in records).isoformat()}
        await self.sync_state.record_success(SOURCE, cursor=cursor)

        if inserted or updated:
            await self.event_bus.publish(
                BATCH_INGESTED,
                {"source": SOURCE, "inserted": inserted, "updated": updated},
            )
        logger.info("ign sync: %d inserted, %d updated (%d fetched)", inserted, updated, len(rows))
        return (inserted, updated)

    @staticmethod
    def _to_row(record: IgnRecord) -> dict[str, Any]:
        attrs = {**record.attrs, "magnitude": record.magnitude, "region": record.region}
        return {
            "source": SOURCE,
            "hazard_type": "earthquake",
            "external_id": record.external_id,
            "geom": point_to_wkb(latitude=record.latitude, longitude=record.longitude),
            "severity": ign_severity(magnitude=record.magnitude),
            "starts_at": record.occurred_at,
            # Un sismo es un evento puntual: su ventana es el propio instante
            # (ADR-0016), asi que nunca cuenta como "vigente ahora".
            "ends_at": record.occurred_at,
            "attrs": attrs,
            # El hash cubre lo que el IGN revisa a posteriori: epicentro,
            # magnitud (dentro de attrs) y hora del evento.
            "content_hash": content_hash(
                {
                    "latitude": record.latitude,
                    "longitude": record.longitude,
                    "attrs": attrs,
                    "occurred_at": record.occurred_at.isoformat(),
                }
            ),
        }


__all__ = ["SOURCE", "SyncIgnUseCase"]
