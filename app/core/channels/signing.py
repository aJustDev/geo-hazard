"""Firma de los webhooks (ADR-0021).

`X-Geohazard-Signature: t=<unix>,v1=<hex HMAC-SHA256(key, "<t>.<body>")>`:
el receptor recalcula el HMAC sobre los bytes exactos del cuerpo y rechaza
las marcas viejas, asi detecta manipulacion y reenvios.
"""

import hashlib
import hmac

SIGNATURE_HEADER = "X-Geohazard-Signature"


def sign(key: str, body: bytes, *, timestamp: int) -> str:
    signed = str(timestamp).encode() + b"." + body
    digest = hmac.new(key.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


__all__ = ["SIGNATURE_HEADER", "sign"]
