"""Un mensaje por suscripcion y ejecucion con todas sus entregas (ADR-0021).
Servicio puro: de entregas pendientes a NtfyMessage o sobre de webhook."""

import uuid
from datetime import datetime
from typing import Any

from app.core.attribution import attributions_for
from app.core.channels.types import NtfyMessage
from app.notifications.schemas.delivery import ClaimedSubscription, PendingDelivery
from app.notifications.schemas.webhook import WebhookArea, WebhookEnvelope, WebhookItem
from app.notifications.services.texts import (
    NOTICE,
    and_more,
    degraded_note,
    phenomenon_name,
    when,
    zone_for,
)

SOURCE_BY_HAZARD = {"weather_warning": "aemet", "earthquake": "ign", "wildfire": "effis"}

# Severidad comun 1-4 (ADR-0009) -> prioridad ntfy; 5 salta el modo silencio.
_NTFY_PRIORITY = {1: 2, 2: 3, 3: 4, 4: 5}
_NTFY_TAGS = {
    "weather_warning": "warning",
    "earthquake": "globe_with_meridians",
    "wildfire": "fire",
}
_MAX_ZONES_IN_LINE = 3


def relevant_degraded(hazard_types: list[str], degraded: list[str]) -> list[str]:
    """Fuentes degradadas de las que depende la suscripcion."""
    wanted = {SOURCE_BY_HAZARD[h] for h in hazard_types if h in SOURCE_BY_HAZARD}
    return sorted(s for s in degraded if s in wanted)


def _props(feature: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = feature.get("properties") or {}
    return props


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def describe(delivery: PendingDelivery) -> tuple[str, str]:
    """(titular, linea) de una entrega. El titular sirve de titulo si el
    mensaje lleva una sola."""
    first = delivery.items[0] if delivery.items else {}
    props = _props(first)
    attrs: dict[str, Any] = props.get("attrs") or {}
    zone = zone_for(first)
    escalated = delivery.reason == "escalated"
    hazard = props.get("hazard_type")

    if hazard == "weather_warning":
        level = attrs.get("level") or "?"
        phenomenon = phenomenon_name(attrs.get("phenomenon"))
        headline = (
            f"Sube a {level} el aviso por {phenomenon}"
            if escalated
            else f"Aviso {level} por {phenomenon}"
        )
        zones: list[str] = []
        for item in delivery.items:
            name = (_props(item).get("attrs") or {}).get("area_desc")
            if name and name not in zones:
                zones.append(name)
        shown = zones[:_MAX_ZONES_IN_LINE]
        hidden = max(delivery.item_count, len(zones)) - len(shown)
        where = ", ".join(shown) or "zona sin nombre"
        if hidden > 0:
            where += f" {and_more(hidden)}"
        window = f"de {when(props.get('starts_at'), zone)} a {when(props.get('ends_at'), zone)}"
        return headline, f"{headline}: {where}, {window}."

    if hazard == "earthquake":
        magnitude = _number(attrs.get("magnitude"))
        size = f"magnitud {magnitude:.1f}" if magnitude is not None else "magnitud ?"
        headline = f"Revisado al alza: terremoto de {size}" if escalated else f"Terremoto de {size}"
        region = attrs.get("region") or "region desconocida"
        return headline, f"{headline} en {region}, {when(props.get('starts_at'), zone)}."

    area_ha = _number(attrs.get("area_ha"))
    extent = f"{area_ha:.0f} ha" if area_ha is not None else "extension desconocida"
    headline = f"Crece el incendio: {extent}" if escalated else f"Incendio de {extent}"
    return headline, f"{headline}, detectado {when(props.get('starts_at'), zone)}."


def _sources(subscription: ClaimedSubscription) -> list[str]:
    return sorted(
        {_props(item).get("source", "") for d in subscription.deliveries for item in d.items} - {""}
    )


def render_ntfy(
    subscription: ClaimedSubscription,
    degraded: list[str],
    *,
    base_url: str,
    max_items: int,
) -> NtfyMessage:
    deliveries = subscription.deliveries
    shown = deliveries[:max_items]
    lines = [describe(d)[1] for d in shown]
    if len(deliveries) > len(shown):
        lines.append(f"{and_more(len(deliveries) - len(shown)).capitalize()} avisos.")

    if len(deliveries) == 1:
        title = f"{describe(deliveries[0])[0]} - {subscription.area_label}"
    else:
        title = f"{len(deliveries)} avisos en {subscription.area_label}"

    footer = [NOTICE, " | ".join(a.text for a in attributions_for(_sources(subscription)))]
    relevant = relevant_degraded(subscription.hazard_types, degraded)
    if relevant:
        footer.append(degraded_note(relevant))

    click = None
    if len(deliveries) == 1 and deliveries[0].item_count == 1 and deliveries[0].items:
        click = f"{base_url.rstrip('/')}/e/{deliveries[0].items[0].get('id')}"

    hazards = {_props(i).get("hazard_type") for d in deliveries for i in d.items}
    return NtfyMessage(
        title=title,
        body="\n".join(lines) + "\n\n" + "\n".join(line for line in footer if line),
        priority=_NTFY_PRIORITY[max(d.severity for d in deliveries)],
        tags=tuple(sorted(_NTFY_TAGS[h] for h in hazards if h in _NTFY_TAGS)),
        click=click,
    )


def render_webhook(
    subscription: ClaimedSubscription,
    degraded: list[str],
    *,
    message_id: uuid.UUID,
    sent_at: datetime,
) -> bytes:
    envelope = WebhookEnvelope(
        message_id=message_id,
        subscription_id=subscription.id,
        sent_at=sent_at,
        area=WebhookArea(id=subscription.area_id, label=subscription.area_label),
        items=[
            WebhookItem(
                delivery_id=d.id,
                episode_id=d.episode_id,
                reason=d.reason,
                severity=d.severity,
                event_count=d.item_count,
                features=d.items,
            )
            for d in subscription.deliveries
        ],
        notice=NOTICE,
        attribution=attributions_for(_sources(subscription)),
        degraded_sources=relevant_degraded(subscription.hazard_types, degraded),
    )
    return envelope.model_dump_json().encode()


__all__ = ["SOURCE_BY_HAZARD", "describe", "relevant_degraded", "render_ntfy", "render_webhook"]
