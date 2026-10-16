import math
from datetime import UTC, datetime, timedelta

import pytest

from app.core.ign.drivers.http import IgnHttpClient
from app.core.ign.exceptions import IgnTransientError

pytestmark = pytest.mark.contract


async def test_feed_georss_del_ign() -> None:
    try:
        records = await IgnHttpClient().fetch_earthquakes()
    except IgnTransientError as exc:
        pytest.skip(f"IGN no disponible: {exc}")

    # Ventana de 10 dias de "Espana y zonas limitrofes": vacia seria anomalo.
    assert records
    now = datetime.now(UTC)
    for r in records:
        assert r.external_id
        assert math.isfinite(r.magnitude)
        assert -90 <= r.latitude <= 90
        assert -180 <= r.longitude <= 180
        assert r.occurred_at.tzinfo is not None
        assert r.occurred_at <= now + timedelta(hours=1)
