from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Tipos canonicos NUESTROS: el adaptador del driver mapea el vocabulario CAP
# de AEMET a esto, y el resto del sistema no sabe como habla Meteoalerta.

MSG_TYPE_ALERT = "Alert"
MSG_TYPE_UPDATE = "Update"
MSG_TYPE_CANCEL = "Cancel"


@dataclass(frozen=True, slots=True)
class AemetWarning:
    """Un aviso CAP de AEMET (un fenomeno sobre una zona) ya normalizado.

    `polygon` conserva la cadena CAP cruda ("lat,lon lat,lon ..."): el swap
    de ejes a (lon, lat) es competencia exclusiva del servicio de geometria.
    Un Cancel puede llegar sin bloque <info>, por eso el contenido es
    opcional; identifier, msgType y sent son lo unico garantizado por CAP.
    """

    external_id: str  # CAP identifier, unico por aviso y zona
    msg_type: str  # Alert | Update | Cancel
    sent: datetime
    references: tuple[str, ...] = ()  # identifiers que este mensaje supersede
    event: str | None = None
    phenomenon: str | None = None  # eventCode "AEMET-Meteoalerta fenomeno"
    level: str | None = None  # parameter "AEMET-Meteoalerta nivel"
    onset: datetime | None = None
    expires: datetime | None = None
    polygon: str | None = None  # CAP crudo "lat,lon lat,lon ..."
    zone: str | None = None  # geocode "AEMET-Meteoalerta zona"
    area_desc: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


__all__ = ["MSG_TYPE_ALERT", "MSG_TYPE_CANCEL", "MSG_TYPE_UPDATE", "AemetWarning"]
