"""Atribucion por fuente (F1, NOTICE): lo que cada licencia exige al
redistribuir dato elaborado."""

from app.core.attribution import ATTRIBUTIONS, attributions_for


def test_solo_las_fuentes_presentes_ordenadas_y_sin_repetir() -> None:
    result = attributions_for(["ign", "effis", "ign", "meteoalarm"])
    assert [a.source for a in result] == ["effis", "ign"]


def test_aemet_exige_la_formula_de_dato_elaborado() -> None:
    # Nota legal de AEMET: dato modificado -> "Fuente: AEMET".
    assert ATTRIBUTIONS["aemet"].text == "Fuente: AEMET"


def test_cada_atribucion_enlaza_sus_terminos() -> None:
    assert all(a.url.startswith("https://") for a in ATTRIBUTIONS.values())
