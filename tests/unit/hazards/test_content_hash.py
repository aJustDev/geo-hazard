from app.hazards.services.content_hash import content_hash


def test_estable_ante_orden_de_claves() -> None:
    assert content_hash({"a": 1, "b": [2, 3]}) == content_hash({"b": [2, 3], "a": 1})


def test_contenido_distinto_hash_distinto() -> None:
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_formato_sha256_hex() -> None:
    digest = content_hash({"k": "v"})
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)
