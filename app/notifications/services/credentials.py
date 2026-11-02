"""Credenciales de los canales (ADR-0021). Servicio puro.

El topic ntfy y la clave HMAC del webhook son el secreto de la suscripcion:
se generan aqui (nunca viajan en argv ni en el historial de la shell), se
muestran una vez y despues solo enmascarados.
"""

import secrets

_NTFY_TOPIC_PREFIX = "geohazard-"


def new_ntfy_topic() -> str:
    # token_urlsafe solo usa [A-Za-z0-9_-], lo que ntfy acepta en un topic;
    # 24 bytes de azar hacen el topic inadivinable (ntfy.sh es publico).
    return _NTFY_TOPIC_PREFIX + secrets.token_urlsafe(24)


def new_webhook_key() -> str:
    return secrets.token_hex(32)


def mask(credential: str) -> str:
    return f"...{credential[-4:]}"


__all__ = ["mask", "new_ntfy_topic", "new_webhook_key"]
