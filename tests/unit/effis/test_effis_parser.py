import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.effis.exceptions import EffisProtocolError
from app.core.effis.parser import parse_burnt_areas, parse_hotspots

FIXTURES = Path(__file__).parents[2] / "fixtures" / "effis"
BA_FIXTURE = FIXTURES / "nrt_ba_poly_week_iberia.geojson"
HS_FIXTURE = FIXTURES / "all_hs_week_iberia.geojson"


def _collection(features: list) -> bytes:
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def _ba_feature(**overrides) -> dict:
    feature = {
        "type": "Feature",
        "properties": {
            "id": "1",
            "fire_id": "77",
            "initialdate": "2026-07-02 12:06:00",
            "finaldate": "2026-07-02 12:23:00",
            "area": "386",
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[42.0, -4.0], [42.1, -4.0], [42.1, -4.1], [42.0, -4.0]]],
        },
    }
    feature.update(overrides)
    return feature


def test_parsea_el_payload_real_de_areas_quemadas() -> None:
    records = parse_burnt_areas(BA_FIXTURE.read_bytes())

    assert len(records) == 84
    first = records[0]
    assert first.external_id == "ba-15411672"
    assert first.kind == "burnt_area"
    assert first.observed_at == datetime(2026, 7, 2, 12, 6, tzinfo=UTC)
    assert first.area_ha == 386.0
    assert first.attrs["raw_finaldate"] == "2026-07-02 12:23:00"
    # El payload real trae Polygon y MultiPolygon; ambos deben sobrevivir.
    assert {r.geometry["type"] for r in records} == {"Polygon", "MultiPolygon"}


def test_parsea_el_payload_real_de_hotspots() -> None:
    records = parse_hotspots(HS_FIXTURE.read_bytes())

    assert len(records) == 40
    first = records[0]
    assert first.external_id == "hs-58860962846"
    assert first.kind == "hotspot"
    assert first.observed_at == datetime(2026, 6, 27, 0, 35, tzinfo=UTC)
    assert first.area_ha is None
    assert first.attrs["class"] == "7DAYS_N"


def test_el_swap_de_ejes_produce_lon_lat_canonico() -> None:
    # gwis serializa [lat, lon]: el primer vertice del payload real es
    # [42.2247245, -4.3348355] (Palencia). En GeoJSON canonico la x es la
    # longitud, asi que el par debe salir invertido.
    first = parse_burnt_areas(BA_FIXTURE.read_bytes())[0]
    lon, lat = first.geometry["coordinates"][0][0]

    assert lon == pytest.approx(-4.3348355)
    assert lat == pytest.approx(42.2247245)

    hotspot = parse_hotspots(HS_FIXTURE.read_bytes())[0]
    assert hotspot.geometry["coordinates"] == pytest.approx([4.89671, 43.44945])


def test_feature_malformado_se_salta_sin_tirar_el_lote() -> None:
    sin_fire_id = _ba_feature(
        properties={"id": "2", "initialdate": "2026-07-02 12:06:00", "area": "10"}
    )
    records = parse_burnt_areas(_collection([_ba_feature(), sin_fire_id]))

    assert len(records) == 1
    assert records[0].external_id == "ba-77"


def test_geometria_inesperada_se_salta() -> None:
    linea = _ba_feature(
        geometry={"type": "LineString", "coordinates": [[42.0, -4.0], [42.1, -4.1]]}
    )
    records = parse_burnt_areas(_collection([_ba_feature(), linea]))

    assert len(records) == 1


def test_ningun_feature_parseable_es_error_de_protocolo() -> None:
    with pytest.raises(EffisProtocolError, match="none of the 1"):
        parse_burnt_areas(_collection([_ba_feature(properties={})]))


def test_payload_no_json_es_error_de_protocolo() -> None:
    # MapServer puede responder XML; el driver lo intercepta antes, pero el
    # parser debe fallar con contrato claro si le llega cualquier no-JSON.
    with pytest.raises(EffisProtocolError, match="unparseable"):
        parse_hotspots(b"<html>mantenimiento</html>")


def test_coleccion_vacia_devuelve_lote_vacio() -> None:
    # Semana sin incendios en el bbox: respuesta valida, no error.
    assert parse_burnt_areas(_collection([])) == []


def test_coordinates_vacias_se_saltan_sin_tirar_el_lote() -> None:
    # Regresion: coordinates [] lanzaba IndexError no capturado y tumbaba el
    # lote entero, contradiciendo el contrato del docstring del parser.
    vacia = _ba_feature(geometry={"type": "Polygon", "coordinates": []})
    records = parse_burnt_areas(_collection([_ba_feature(), vacia]))

    assert len(records) == 1
    assert records[0].external_id == "ba-77"


def test_vertice_fuera_de_rango_se_salta() -> None:
    # Sanity del swap de ejes: una "latitud" de 142 grados es imposible; si
    # el upstream corrigiera la ordenacion en silencio, esto lo delataria.
    fuera = _ba_feature(
        geometry={
            "type": "Polygon",
            "coordinates": [[[142.0, -4.0], [42.1, -4.0], [42.1, -4.1], [142.0, -4.0]]],
        }
    )
    records = parse_burnt_areas(_collection([_ba_feature(), fuera]))

    assert len(records) == 1


def test_area_no_finita_se_salta() -> None:
    # float() acepta "1e999" (inf) y "nan"; ninguno debe llegar a severity.
    for area in ("1e999", "nan"):
        props = {"id": "3", "fire_id": "99", "initialdate": "2026-07-02 12:06:00", "area": area}
        records = parse_burnt_areas(_collection([_ba_feature(), _ba_feature(properties=props)]))

        assert len(records) == 1
