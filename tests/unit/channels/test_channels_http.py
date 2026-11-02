import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from app.core.channels import guard
from app.core.channels.drivers.http import NTFY_MAX_BODY_BYTES, HttpChannelSender
from app.core.channels.signing import SIGNATURE_HEADER
from app.core.channels.types import ChannelError, NtfyMessage
from app.core.config import settings

WEBHOOK = "https://hooks.example.com/services/SECRET-PATH"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["159.203.148.75"]

    monkeypatch.setattr(guard, "_resolve", fake_resolve)


def _sender(handler) -> HttpChannelSender:
    return HttpChannelSender(transport=httpx.MockTransport(handler))


async def test_ntfy_publica_json_en_la_raiz() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["json"] = json.loads(request.content)
        seen["user_agent"] = request.headers["user-agent"]
        return httpx.Response(200, json={"id": "x"})

    message = NtfyMessage(
        title="Aviso naranja: Tormentas en Murcia",
        body="Vega del Segura",
        priority=4,
        tags=("warning",),
        click="https://geohazard.ajustino.dev/v1/events/1",
    )
    await _sender(handler).send_ntfy(
        server="https://ntfy.sh", topic="geohazard-t0p", message=message
    )

    assert seen["method"] == "POST"
    # El topic va en el cuerpo, no en la URL (que acaba en logs de proxies).
    assert seen["url"] == "https://ntfy.sh/"
    assert seen["json"] == {
        "topic": "geohazard-t0p",
        "title": "Aviso naranja: Tormentas en Murcia",
        "message": "Vega del Segura",
        "priority": 4,
        "tags": ["warning"],
        "click": "https://geohazard.ajustino.dev/v1/events/1",
    }
    assert str(seen["user_agent"]).startswith("geo-hazard/")


async def test_ntfy_sin_click_y_titulo_utf8() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200)

    message = NtfyMessage(title="Fenómenos costeros en Almería", body="x")
    await _sender(handler).send_ntfy(server="https://ntfy.sh/", topic="t", message=message)

    assert bodies[0]["title"] == "Fenómenos costeros en Almería"
    assert "click" not in bodies[0]


async def test_ntfy_corta_el_cuerpo_en_frontera_utf8() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200)

    message = NtfyMessage(title="t", body="á" * 3000)  # 6000 bytes
    await _sender(handler).send_ntfy(server="https://ntfy.sh", topic="t", message=message)

    sent = bodies[0]["message"]
    assert len(sent.encode()) <= NTFY_MAX_BODY_BYTES
    assert set(sent) == {"á"}


async def test_webhook_firmado_sobre_los_bytes_exactos() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        seen["signature"] = request.headers[SIGNATURE_HEADER]
        seen["content_type"] = request.headers["content-type"]
        return httpx.Response(204)

    body = b'{"version":1,"items":[]}'
    await _sender(handler).send_webhook(url=WEBHOOK, key="k" * 64, body=body)

    assert seen["url"] == WEBHOOK
    assert seen["body"] == body
    assert seen["content_type"] == "application/json"
    t_part, v1_part = str(seen["signature"]).split(",")
    ts = t_part.removeprefix("t=")
    expected = hmac.new(b"k" * 64, f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    assert v1_part == f"v1={expected}"


@pytest.mark.parametrize("status", [302, 400, 404, 500, 503])
async def test_respuesta_no_2xx_es_error_sin_la_ruta(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"location": "https://elsewhere.example"})

    with pytest.raises(ChannelError) as excinfo:
        await _sender(handler).send_webhook(url=WEBHOOK, key="k", body=b"{}")

    assert str(status) in str(excinfo.value)
    assert "SECRET" not in str(excinfo.value)
    assert "https://hooks.example.com" in str(excinfo.value)


async def test_error_de_red_sin_la_ruta() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused to /services/SECRET-PATH")

    with pytest.raises(ChannelError) as excinfo:
        await _sender(handler).send_webhook(url=WEBHOOK, key="k", body=b"{}")

    assert "ConnectError" in str(excinfo.value)
    assert "SECRET" not in str(excinfo.value)


async def test_tiempo_total_acotado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "NOTIFICATIONS_HTTP_TIMEOUT_SECONDS", 0.05)

    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200)

    with pytest.raises(ChannelError, match="timeout"):
        await _sender(slow).send_webhook(url=WEBHOOK, key="k", body=b"{}")


async def test_host_privado_no_llega_a_salir(monkeypatch: pytest.MonkeyPatch) -> None:
    async def private(host: str, port: int) -> list[str]:
        return ["10.0.0.7"]

    monkeypatch.setattr(guard, "_resolve", private)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    with pytest.raises(ChannelError, match="non-public"):
        await _sender(handler).send_webhook(url=WEBHOOK, key="k", body=b"{}")
    with pytest.raises(ChannelError, match="non-public"):
        await _sender(handler).check_endpoint(WEBHOOK)
    assert calls == []
