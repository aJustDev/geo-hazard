"""Hash canonico del contenido de un evento (ADR-0008). Servicio puro.

El upsert solo escribe (y solo emite evento) cuando este hash cambia: las
fuentes re-sirven los mismos registros en cada poll y los poligonos de un
incendio activo crecen entre polls; el hash separa "re-servido identico" de
"cambio real".
"""

import hashlib
import json
from typing import Any


def content_hash(payload: dict[str, Any]) -> str:
    """sha256 hex (64 chars) de la serializacion canonica del payload.

    sort_keys + separadores compactos: el mismo contenido produce siempre el
    mismo hash aunque el orden de claves del origen cambie.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["content_hash"]
