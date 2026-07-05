"""Utilidades HTTP compartidas por los drivers de fuentes (ADR-0017).

Los upstreams se leen por streaming con un tope de bytes acumulados: una
respuesta gigante (upstream defectuoso o mirror comprometido) se corta antes
de agotar la RAM del worker, en vez de materializarse entera con
`response.content`.
"""

import httpx


class ResponseTooLargeError(Exception):
    """El cuerpo de la respuesta supero el tope de bytes permitido."""


async def get_capped(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_bytes: int,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    """GET por streaming con corte por bytes. Devuelve (status_code, body).

    El cuerpo solo se lee si el status es 200: un 4xx/5xx no necesita cuerpo
    (y podria ser igual de grande). Si el acumulado supera `max_bytes`, aborta
    con ResponseTooLargeError; quien llama lo mapea a su *TransientError.
    """
    async with client.stream("GET", url, params=params, headers=headers) as response:
        if response.status_code != 200:
            return response.status_code, b""
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > max_bytes:
                raise ResponseTooLargeError(f"response body exceeded {max_bytes} bytes")
        return response.status_code, bytes(body)


__all__ = ["ResponseTooLargeError", "get_capped"]
