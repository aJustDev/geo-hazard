import pytest

from app.notifications.services.areas import (
    BboxArea,
    CircleArea,
    ProvinceArea,
    bbox_area,
    circle_area,
    province_area,
)


def test_provincia_dos_cifras_ine() -> None:
    assert province_area("30") == ProvinceArea(code="30")


@pytest.mark.parametrize("code", ["3", "300", "M1", "", " 30"])
def test_provincia_mal_formada(code: str) -> None:
    with pytest.raises(ValueError, match="two INE digits"):
        province_area(code)


def test_bbox_valido_y_etiqueta() -> None:
    area = bbox_area("-1.5,37.5,-0.7,38.0")
    assert area == BboxArea(-1.5, 37.5, -0.7, 38.0)
    assert area.label == "rectangulo -1.5,37.5,-0.7,38.0"


@pytest.mark.parametrize("raw", ["-1,37,-2,38", "1,2,3", "a,b,c,d", "-1,91,0,92"])
def test_bbox_invalido(raw: str) -> None:
    with pytest.raises(ValueError):
        bbox_area(raw)


def test_circulo_en_km_a_metros() -> None:
    area = circle_area("-0.99,37.62,30")
    assert area == CircleArea(lon=-0.99, lat=37.62, radius_m=30_000)
    assert area.label == "30 km alrededor de 37.62,-0.99"


@pytest.mark.parametrize("km", ["1", "200", "12.5"])
def test_circulo_radio_en_rango(km: str) -> None:
    assert circle_area(f"-0.99,37.62,{km}").radius_m == round(float(km) * 1000)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("-0.99,37.62,0.5", "radius"),
        ("-0.99,37.62,201", "radius"),
        ("-0.99,37.62,nan", "radius"),
        ("-0.99,37.62,inf", "radius"),
        ("-181,37.62,10", "center"),
        ("-0.99,nan,10", "center"),
        ("-0.99,37.62", "lon,lat,km"),
    ],
)
def test_circulo_invalido(raw: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        circle_area(raw)
