from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.ign.exceptions import IgnProtocolError
from app.core.ign.parser import parse_georss

FIXTURE = Path(__file__).parents[2] / "fixtures" / "ign" / "georss_ultimos_10_dias.xml"

_ITEM_OK = """
<item>
  <title>-Info.terremoto: 02/07/2026 7:06:37</title>
  <guid>http://www.ign.es/web/x?evid=es2026aaaaa</guid>
  <description>Se ha producido un terremoto de magnitud 3.5 en GOLFO DE C\u00c1DIZ en la fecha 02/07/2026 7:06:37 en la siguiente localizaci\u00f3n: 36.6366,-8.0798</description>
  <geo:lat>36.6366</geo:lat>
  <geo:long>-8.0798</geo:long>
</item>
"""


def _feed(items: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss xmlns:geo="http://www.w3.org/2003/01/geo/wgs84_pos#" version="2.0">'
        f"<channel>{items}</channel></rss>"
    ).encode()


def test_parsea_el_feed_real_completo() -> None:
    records = parse_georss(FIXTURE.read_bytes())

    assert len(records) == 14
    first = records[0]
    assert first.external_id == "es2026mvdms"
    assert first.magnitude == 3.5
    assert first.region == "GOLFO DE C\u00c1DIZ"
    assert first.latitude == 36.6366
    assert first.longitude == -8.0798


def test_la_hora_local_se_convierte_a_utc() -> None:
    # 02/07/2026 7:06:37 hora peninsular (julio = CEST, UTC+2) -> 05:06:37Z.
    # La cadena original sobrevive en attrs por si la doctrina de zona
    # horaria resultara equivocada.
    first = parse_georss(FIXTURE.read_bytes())[0]

    assert first.occurred_at == datetime(2026, 7, 2, 5, 6, 37, tzinfo=UTC)
    assert first.attrs["raw_local_moment"] == "02/07/2026 7:06:37"


def test_item_malformado_se_salta_sin_tirar_el_feed() -> None:
    sin_evid = _ITEM_OK.replace("?evid=es2026aaaaa", "")
    records = parse_georss(_feed(_ITEM_OK + sin_evid))

    assert len(records) == 1
    assert records[0].external_id == "es2026aaaaa"


def test_feed_ilegible_es_error_de_protocolo() -> None:
    with pytest.raises(IgnProtocolError, match="unparseable"):
        parse_georss(b"esto no es xml")


def test_ningun_item_parseable_es_error_de_protocolo() -> None:
    # Hay items pero ninguno se entiende: cambio de contrato, no feed vacio.
    sin_evid = _ITEM_OK.replace("?evid=es2026aaaaa", "")
    with pytest.raises(IgnProtocolError, match="none of the"):
        parse_georss(_feed(sin_evid))


def test_feed_vacio_es_lista_vacia() -> None:
    assert parse_georss(_feed("")) == []
