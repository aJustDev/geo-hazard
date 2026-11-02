"""Envio real por ntfy y webhook (ADR-0021).

Cada envio pasa la guarda de salida, no sigue redirecciones, ignora proxies
del entorno (saltarian la guarda) y tiene un tiempo total acotado: los
timeouts de httpx son por fase, no por peticion. Ningun error lleva la URL:
un webhook de Slack o Discord trae el secreto en la ruta.
"""

import asyncio
import time

import httpx

from app.core.channels.guard import assert_public_https, describe
from app.core.channels.signing import SIGNATURE_HEADER, sign
from app.core.channels.types import ChannelError, NtfyMessage
from app.core.config import settings
from app.core.http import USER_AGENT

# Limite de ntfy para el cuerpo de un mensaje; por encima lo convierte en
# adjunto. Se corta en frontera UTF-8.
NTFY_MAX_BODY_BYTES = 4096


def _cap_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode()
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode(errors="ignore")


class HttpChannelSender:
    """Cumple el Protocol ChannelSender. `transport` inyectable para tests."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def check_endpoint(self, url: str) -> None:
        await assert_public_https(url)

    async def send_ntfy(self, *, server: str, topic: str, message: NtfyMessage) -> None:
        # Publicacion JSON en la raiz del servidor: el topic no aparece en la
        # URL y el titulo puede llevar UTF-8 (en cabeceras no).
        payload = {
            "topic": topic,
            "title": message.title,
            "message": _cap_utf8(message.body, NTFY_MAX_BODY_BYTES),
            "priority": message.priority,
            "tags": list(message.tags),
        }
        if message.click:
            payload["click"] = message.click
        await self._post(server.rstrip("/") + "/", json=payload)

    async def send_webhook(self, *, url: str, key: str, body: bytes) -> None:
        headers = {
            "Content-Type": "application/json",
            SIGNATURE_HEADER: sign(key, body, timestamp=int(time.time())),
        }
        await self._post(url, content=body, headers=headers)

    async def _post(
        self,
        url: str,
        *,
        json: object = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        await assert_public_https(url)
        target = describe(url)
        try:
            async with asyncio.timeout(settings.NOTIFICATIONS_HTTP_TIMEOUT_SECONDS):
                async with httpx.AsyncClient(
                    timeout=settings.NOTIFICATIONS_HTTP_TIMEOUT_SECONDS,
                    transport=self._transport,
                    headers={"User-Agent": USER_AGENT},
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    response = await client.post(url, json=json, content=content, headers=headers)
        except TimeoutError as exc:
            raise ChannelError(f"timeout sending to {target}") from exc
        except httpx.HTTPError as exc:
            raise ChannelError(f"{type(exc).__name__} sending to {target}") from exc
        if not response.is_success:
            raise ChannelError(f"{target} answered {response.status_code}")


__all__ = ["NTFY_MAX_BODY_BYTES", "HttpChannelSender"]
