import hashlib
import hmac

from app.core.channels.signing import sign


def test_firma_verificable_con_hmac_independiente() -> None:
    key, body, ts = "k" * 64, b'{"version":1}', 1793640000
    header = sign(key, body, timestamp=ts)

    t_part, v1_part = header.split(",")
    assert t_part == f"t={ts}"
    expected = hmac.new(key.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    assert v1_part == f"v1={expected}"


def test_la_marca_de_tiempo_entra_en_la_firma() -> None:
    assert sign("k", b"{}", timestamp=1) != sign("k", b"{}", timestamp=2)
