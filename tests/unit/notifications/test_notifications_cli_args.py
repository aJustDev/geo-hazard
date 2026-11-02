import pytest

from app.notifications.cli import _area, _channel, _parser


def _parse(*argv: str):
    return _parser().parse_args(list(argv))


BASE = ("add", "--types", "earthquake", "--severity-min", "2")


def test_add_exige_un_area_y_un_canal() -> None:
    with pytest.raises(SystemExit):
        _parse(*BASE, "--ntfy")  # sin area
    with pytest.raises(SystemExit):
        _parse(*BASE, "--province", "30")  # sin canal
    with pytest.raises(SystemExit):
        _parse(*BASE, "--province", "30", "--circle", "-1,38,10", "--ntfy")
    with pytest.raises(SystemExit):
        _parse(*BASE, "--province", "30", "--ntfy", "--webhook", "https://h.example")


@pytest.mark.parametrize("severity", ["0", "5", "x"])
def test_severidad_de_1_a_4(severity: str) -> None:
    with pytest.raises(SystemExit):
        _parse(
            "add", "--types", "earthquake", "--severity-min", severity, "--province", "30", "--ntfy"
        )


def test_area_y_canal_desde_argumentos() -> None:
    args = _parse(*BASE, "--circle", "-0.99,37.62,30", "--ntfy")
    assert _area(args).radius_m == 30_000
    channel = _channel(args)
    assert (channel.kind, channel.endpoint) == ("ntfy", "https://ntfy.sh")

    args = _parse(*BASE, "--bbox", "-1.5,37.5,-0.7,38.0", "--webhook", "https://h.example/x")
    assert _area(args).min_lon == -1.5
    assert _channel(args).endpoint == "https://h.example/x"


def test_ids_como_uuid() -> None:
    with pytest.raises(SystemExit):
        _parse("pause", "no-es-un-uuid")
