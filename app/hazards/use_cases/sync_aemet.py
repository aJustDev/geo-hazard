import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.aemet.driver import AemetClient
from app.core.aemet.types import MSG_TYPE_ALERT, MSG_TYPE_CANCEL, MSG_TYPE_UPDATE, AemetWarning
from app.core.events.bus import EventBus
from app.hazards.repos.hazard_event import HazardEventRepo
from app.hazards.repos.sync_state import SourceSyncStateRepo
from app.hazards.services.content_hash import content_hash
from app.hazards.services.geometry import cap_polygon_to_wkb
from app.hazards.services.severity import aemet_severity
from app.hazards.use_cases.sync_effis import BATCH_INGESTED

logger = logging.getLogger(__name__)

SOURCE = "aemet"


@dataclass(slots=True)
class SyncAemetUseCase:
    """Reconcilia el boletin "ultimo elaborado" de Meteoalerta (ADR-0010).

    El boletin es el set COMPLETO de avisos en vigor, y de ahi derivan las
    tres reglas del ciclo de vida:

    - Alert/Update con nivel amarillo o superior se ingieren (verde es la
      ausencia de riesgo; un Cancel no es un aviso).
    - Update/Cancel cierran los avisos que referencian: ends_at pasa a ser
      el sent del mensaje que los supersede.
    - Un aviso del cursor anterior que desaparece del boletin sin Cancel se
      cierra a "ahora": AEMET lo retiro al elaborar el boletin nuevo.

    No commitea: la frontera de transaccion es del job handler.
    """

    repo: HazardEventRepo
    sync_state: SourceSyncStateRepo
    event_bus: EventBus

    async def execute(self, *, client: AemetClient) -> tuple[int, int, int]:
        warnings = await client.fetch_warnings()

        ingestible = [w for w in warnings if self._is_ingestible(w)]
        inserted, updated = await self.repo.upsert_batch([self._to_row(w) for w in ingestible])

        closed = await self._close_superseded(warnings)
        closed += await self._close_vanished(ingestible)

        await self.sync_state.record_success(
            SOURCE, cursor={"identifiers": sorted(w.external_id for w in ingestible)}
        )

        if inserted or updated or closed:
            await self.event_bus.publish(
                BATCH_INGESTED,
                {"source": SOURCE, "inserted": inserted, "updated": updated, "closed": closed},
            )
        logger.info(
            "aemet sync: %d inserted, %d updated, %d closed (%d in bulletin)",
            inserted,
            updated,
            closed,
            len(warnings),
        )
        return (inserted, updated, closed)

    @staticmethod
    def _is_ingestible(warning: AemetWarning) -> bool:
        if warning.msg_type not in (MSG_TYPE_ALERT, MSG_TYPE_UPDATE):
            return False
        if warning.level is None or warning.level.strip().lower() == "verde":
            return False
        if not (warning.polygon and warning.onset and warning.expires):
            # Sin geometria o sin ventana no hay evento representable.
            logger.warning("aemet warning %s skipped: incomplete CAP", warning.external_id)
            return False
        return True

    async def _close_superseded(self, warnings: list[AemetWarning]) -> int:
        # Agrupado por sent: todos los CAP de un mismo boletin comparten
        # timestamp de elaboracion, asi que esto son 1-2 UPDATEs, no cientos.
        by_sent: dict[datetime, set[str]] = {}
        for warning in warnings:
            if warning.msg_type in (MSG_TYPE_UPDATE, MSG_TYPE_CANCEL) and warning.references:
                by_sent.setdefault(warning.sent, set()).update(warning.references)
        closed = 0
        for sent, identifiers in by_sent.items():
            closed += await self.repo.close_events(
                source=SOURCE, external_ids=identifiers, ended_at=sent
            )
        return closed

    async def _close_vanished(self, ingestible: list[AemetWarning]) -> int:
        state = await self.sync_state.get(SOURCE)
        previous = set(state.cursor.get("identifiers", [])) if state is not None else set()
        vanished = previous - {w.external_id for w in ingestible}
        if not vanished:
            return 0
        return await self.repo.close_events(
            source=SOURCE, external_ids=vanished, ended_at=datetime.now(UTC)
        )

    @staticmethod
    def _to_row(warning: AemetWarning) -> dict[str, Any]:
        if not (warning.level and warning.polygon and warning.onset and warning.expires):
            raise ValueError("not an ingestible warning")  # _is_ingestible lo garantiza
        attrs = {
            key: value
            for key, value in {
                "event": warning.event,
                "phenomenon": warning.phenomenon,
                "level": warning.level,
                "zone": warning.zone,
                "area_desc": warning.area_desc,
                **warning.attrs,
            }.items()
            if value is not None
        }
        return {
            "source": SOURCE,
            "hazard_type": "weather_warning",
            "external_id": warning.external_id,
            "geom": cap_polygon_to_wkb(warning.polygon),
            "severity": aemet_severity(nivel=warning.level),
            "starts_at": warning.onset,
            "ends_at": warning.expires,
            "attrs": attrs,
            # El hash cubre lo que define "cambio real" en un aviso: zona,
            # contenido y ventana de vigencia.
            "content_hash": content_hash(
                {
                    "polygon": warning.polygon,
                    "attrs": attrs,
                    "onset": warning.onset.isoformat(),
                    "expires": warning.expires.isoformat(),
                }
            ),
        }


__all__ = ["SOURCE", "SyncAemetUseCase"]
