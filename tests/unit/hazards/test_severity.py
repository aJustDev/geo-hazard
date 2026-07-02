import pytest

from app.hazards.services.severity import effis_severity


def test_hotspot_es_2_fijo() -> None:
    assert effis_severity(kind="hotspot") == 2
    assert effis_severity(kind="hotspot", area_ha=99999.0) == 2


@pytest.mark.parametrize(
    ("area_ha", "expected"),
    [(None, 2), (30.0, 2), (499.9, 2), (500.0, 3), (4999.0, 3), (5000.0, 4)],
)
def test_area_quemada_escala_por_hectareas(area_ha: float | None, expected: int) -> None:
    assert effis_severity(kind="burnt_area", area_ha=area_ha) == expected


def test_kind_desconocido_rechazado() -> None:
    with pytest.raises(ValueError, match="unknown"):
        effis_severity(kind="volcano")
