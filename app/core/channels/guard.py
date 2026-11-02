"""Guarda de salida: solo https hacia hosts publicos (ADR-0021).

La API comparte servidor con otros servicios; un endpoint que resuelva a
loopback o a una red privada convertiria los avisos en una puerta hacia
ellos. Se comprueba al crear la suscripcion y antes de cada envio. No fija
la IP resuelta (DNS rebinding queda fuera mientras solo el operador cree
suscripciones; ver el ADR).
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from app.core.channels.types import ChannelError


async def _resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def describe(url: str) -> str:
    """'https://host' para logs y errores: sin ruta, query ni credenciales."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname or '?'}"


async def assert_public_https(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ChannelError(f"endpoint must be https with a host: {describe(url)}")
    try:
        addresses = await _resolve(parts.hostname, parts.port or 443)
    except OSError as exc:
        raise ChannelError(f"cannot resolve {describe(url)}: {type(exc).__name__}") from exc
    if not addresses:
        raise ChannelError(f"cannot resolve {describe(url)}")
    for raw in addresses:
        address = ipaddress.ip_address(raw.split("%", 1)[0])
        if not address.is_global or address.is_multicast:
            raise ChannelError(f"{describe(url)} resolves to a non-public address")


__all__ = ["assert_public_https", "describe"]
