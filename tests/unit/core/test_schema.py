from app.core.schema import BaseSchema
from app.deps.database import get_session


class ThingRead(BaseSchema):
    name: str


class _Obj:
    name = "hola"


def test_base_schema_valida_desde_atributos() -> None:
    assert ThingRead.model_validate(_Obj()).name == "hola"


def test_deps_reexporta_get_session() -> None:
    # El paquete deps es la superficie publica de inyeccion para los routers.
    assert callable(get_session)
