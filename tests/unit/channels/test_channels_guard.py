import pytest

from app.core.channels import guard
from app.core.channels.guard import assert_public_https, describe
from app.core.channels.types import ChannelError


def _resolving_to(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return list(addresses)

    monkeypatch.setattr(guard, "_resolve", fake_resolve)


async def test_https_publico_pasa(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolving_to(monkeypatch, "159.203.148.75", "2604:a880:400:d0::1")
    await assert_public_https("https://ntfy.sh")


@pytest.mark.parametrize("url", ["http://ntfy.sh", "ftp://ntfy.sh", "https://", "ntfy.sh"])
async def test_solo_https_con_host(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    _resolving_to(monkeypatch, "159.203.148.75")
    with pytest.raises(ChannelError, match="https"):
        await assert_public_https(url)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.3.4",
        "192.168.1.1",
        "169.254.169.254",  # metadatos de nube
        "100.64.0.1",  # CGNAT
        "0.0.0.0",  # noqa: S104 - es el valor bajo prueba, no un bind
        "224.0.0.1",
        "::1",
        "::ffff:127.0.0.1",
        "fc00::1",
        "fe80::1%eth0",
    ],
)
async def test_direcciones_no_publicas_rechazadas(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    _resolving_to(monkeypatch, address)
    with pytest.raises(ChannelError, match="non-public"):
        await assert_public_https("https://hooks.example.com/x")


async def test_una_direccion_privada_entre_publicas_basta_para_rechazar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _resolving_to(monkeypatch, "159.203.148.75", "10.0.0.1")
    with pytest.raises(ChannelError, match="non-public"):
        await assert_public_https("https://hooks.example.com")


async def test_host_que_no_resuelve(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing(host: str, port: int) -> list[str]:
        raise OSError("Name or service not known")

    monkeypatch.setattr(guard, "_resolve", failing)
    with pytest.raises(ChannelError, match="cannot resolve https://nope.invalid"):
        await assert_public_https("https://nope.invalid/secret-path")


async def test_resolucion_vacia(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolving_to(monkeypatch)
    with pytest.raises(ChannelError, match="cannot resolve"):
        await assert_public_https("https://hooks.example.com")


async def test_resolucion_real_de_localhost() -> None:
    # Sin monkeypatch: getaddrinfo de verdad, que nunca devuelve algo publico.
    with pytest.raises(ChannelError, match="non-public"):
        await assert_public_https("https://localhost:8443")


def test_describe_oculta_ruta_query_y_credenciales() -> None:
    url = "https://user:pass@hooks.slack.com/services/T000/B000/SECRET?x=1"
    assert describe(url) == "https://hooks.slack.com"
