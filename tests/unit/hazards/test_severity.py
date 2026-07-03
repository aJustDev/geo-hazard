import pytest

from app.hazards.services.severity import aemet_severity, effis_severity, ign_severity


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


@pytest.mark.parametrize(
    ("magnitude", "expected"),
    [(1.5, 1), (2.9, 1), (3.0, 2), (3.9, 2), (4.0, 3), (5.4, 3), (5.5, 4), (7.0, 4)],
)
def test_ign_escala_por_magnitud(magnitude: float, expected: int) -> None:
    assert ign_severity(magnitude=magnitude) == expected


@pytest.mark.parametrize(
    ("nivel", "expected"),
    [("verde", 1), ("amarillo", 2), ("naranja", 3), ("rojo", 4)],
)
def test_aemet_mapea_niveles_meteoalerta(nivel: str, expected: int) -> None:
    assert aemet_severity(nivel=nivel) == expected


def test_aemet_normaliza_mayusculas_y_espacios() -> None:
    assert aemet_severity(nivel=" Naranja ") == 3


def test_aemet_nivel_desconocido_rechazado() -> None:
    with pytest.raises(ValueError, match="unknown"):
        aemet_severity(nivel="morado")
