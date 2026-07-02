import uuid
from datetime import UTC, datetime

import pytest

from app.hazards.services.pagination import decode_cursor, encode_cursor


def test_roundtrip() -> None:
    starts_at = datetime(2026, 7, 1, 13, 30, tzinfo=UTC)
    event_id = uuid.uuid4()
    cursor = encode_cursor(starts_at=starts_at, event_id=event_id)
    assert decode_cursor(cursor) == (starts_at, event_id)


@pytest.mark.parametrize("garbage", ["", "no-base64!", "aGVsbG8=", "eyJrIjoxfQ=="])
def test_cursor_corrupto_rechazado(garbage: str) -> None:
    with pytest.raises(ValueError, match="invalid cursor"):
        decode_cursor(garbage)
