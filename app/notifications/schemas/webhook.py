"""Sobre JSON de los webhooks, version 1 (ADR-0021).

Contrato publico para quien recibe los avisos: anadir campos es compatible,
quitarlos o cambiar su significado exige `version` 2.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from app.core.attribution import SourceAttribution
from app.core.schema import BaseSchema


class WebhookArea(BaseSchema):
    id: uuid.UUID
    label: str


class WebhookItem(BaseSchema):
    # Para deduplicar: la entrega es al menos una vez (ADR-0021).
    delivery_id: uuid.UUID
    episode_id: uuid.UUID
    reason: Literal["opened", "escalated"]
    severity: int
    # Cuantos eventos casaron; `features` puede traer menos.
    event_count: int
    features: list[dict[str, Any]]


class WebhookEnvelope(BaseSchema):
    version: Literal[1] = 1
    message_id: uuid.UUID
    subscription_id: uuid.UUID
    sent_at: datetime
    area: WebhookArea
    items: list[WebhookItem]
    notice: str
    attribution: list[SourceAttribution]
    # Fuentes de las que depende la suscripcion y estan degradadas: un
    # silencio suyo no significa "no pasa nada".
    degraded_sources: list[str]


__all__ = ["WebhookArea", "WebhookEnvelope", "WebhookItem"]
