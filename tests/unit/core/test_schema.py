from app.core.schema import BaseSchema


class ThingRead(BaseSchema):
    name: str


class _Obj:
    name = "hola"


def test_base_schema_valida_desde_atributos() -> None:
    assert ThingRead.model_validate(_Obj()).name == "hola"
