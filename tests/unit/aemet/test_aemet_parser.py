from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.aemet.exceptions import AemetProtocolError
from app.core.aemet.parser import parse_cap

FIXTURE = Path(__file__).parents[2] / "fixtures" / "aemet" / "cap_aviso_naranja_ta.xml"

_CANCEL = """<?xml version="1.0" encoding="UTF-8"?>
<alert xmlns = "urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>cancel-1</identifier>
  <sender>http://www.aemet.es</sender>
  <sent>2026-07-02T18:00:00-00:00</sent>
  <status>Actual</status>
  <msgType>Cancel</msgType>
  <scope>Public</scope>
  <references>http://www.aemet.es,viejo-1,2026-07-01T08:44:31-00:00</references>
</alert>
"""


def test_parsea_el_cap_real() -> None:
    warning = parse_cap(FIXTURE.read_bytes())

    assert warning.external_id == "2.49.0.0.724.0.ES.20260702162803.700602ATTA03191783009683"
    assert warning.msg_type == "Update"
    assert warning.sent == datetime(2026, 7, 2, 16, 28, 3, tzinfo=UTC)
    assert warning.references == (
        "2.49.0.0.724.0.ES.20260701084431.700602ATTA02191782895471",
        "2.49.0.0.724.0.ES.20260702091157.700602ATTA03191782983517",
    )


def test_toma_el_bloque_info_castellano() -> None:
    # El CAP duplica <info> en es-ES y en-GB; el canonico es el castellano.
    warning = parse_cap(FIXTURE.read_bytes())

    assert warning.event == "Aviso de temperaturas m\u00e1ximas de nivel naranja"
    assert warning.level == "naranja"
    assert warning.phenomenon == "AT;Temperaturas m\u00e1ximas"
    assert warning.zone == "700602"
    assert warning.area_desc == "La Siberia extreme\u00f1a"
    assert warning.attrs["probability"] == "40%-70%"
    assert warning.attrs["cap_severity"] == "Severe"


def test_ventana_de_vigencia_con_offset() -> None:
    # onset/expires llegan con offset +02:00 y deben conservarlo.
    warning = parse_cap(FIXTURE.read_bytes())
    cest = timezone(timedelta(hours=2))

    assert warning.onset == datetime(2026, 7, 3, 13, 0, 0, tzinfo=cest)
    assert warning.expires == datetime(2026, 7, 3, 20, 59, 59, tzinfo=cest)


def test_el_poligono_se_conserva_crudo() -> None:
    # El swap de ejes (lat,lon -> lon,lat) NO es cosa del parser: la cadena
    # CAP viaja intacta hasta el servicio de geometria.
    warning = parse_cap(FIXTURE.read_bytes())

    assert warning.polygon is not None
    assert warning.polygon.startswith("39.14,-5.58 39.19,-5.61")


def test_cancel_sin_info_devuelve_solo_referencias() -> None:
    warning = parse_cap(_CANCEL.encode())

    assert warning.msg_type == "Cancel"
    assert warning.references == ("viejo-1",)
    assert warning.level is None
    assert warning.polygon is None


def test_xml_ilegible_es_error_de_protocolo() -> None:
    with pytest.raises(AemetProtocolError, match="unparseable"):
        parse_cap(b"esto no es xml")


def test_cap_sin_identifier_es_error_de_protocolo() -> None:
    sin_identifier = _CANCEL.replace("<identifier>cancel-1</identifier>", "")
    with pytest.raises(AemetProtocolError, match="missing"):
        parse_cap(sin_identifier.encode())
