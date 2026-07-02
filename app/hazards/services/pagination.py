"""Cursor keyset opaco para la paginacion de eventos (ADR-0006). Puro.

Keyset sobre (starts_at DESC, id DESC) en vez de OFFSET: el offset degrada
linealmente y se descoloca cuando una ingesta inserta filas entre pagina y
pagina; la tupla (starts_at, id) es estable bajo escrituras concurrentes.
El cursor viaja opaco (base64 de JSON) para que el cliente no acople nada
a su forma interna.
"""

import base64
import binascii
import json
import uuid
from datetime import datetime


def encode_cursor(*, starts_at: datetime, event_id: uuid.UUID) -> str:
    raw = json.dumps([starts_at.isoformat(), str(event_id)])
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Inverso de encode_cursor. ValueError ante cualquier cursor corrupto."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        starts_at_iso, event_id = json.loads(raw)
        return (datetime.fromisoformat(starts_at_iso), uuid.UUID(event_id))
    except (binascii.Error, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid cursor: {cursor!r}") from exc


__all__ = ["decode_cursor", "encode_cursor"]
