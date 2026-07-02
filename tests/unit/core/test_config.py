import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make(**overrides: object) -> Settings:
    # _env_file=None evita cargar el .env.local del desarrollador en los tests.
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_database_url_derivada_de_las_partes() -> None:
    s = make(DB_HOST="h", DB_PORT=5, DB_USER="u", DB_PASSWORD="p", DB_NAME="n")
    assert s.DATABASE_URL == "postgresql+asyncpg://u:p@h:5/n"


def test_database_url_explicita_gana() -> None:
    s = make(DATABASE_URL="postgresql+asyncpg://x:y@z:1/w")
    assert s.DATABASE_URL == "postgresql+asyncpg://x:y@z:1/w"


def test_cors_origins_parsea_y_limpia() -> None:
    s = make(CORS_ORIGINS=" https://a.example ,https://b.example, ")
    assert s.cors_origins == ["https://a.example", "https://b.example"]


def test_lease_menor_que_dos_timeouts_rechazado() -> None:
    with pytest.raises(ValidationError, match="JOB_LEASE_SECONDS"):
        make(JOB_LEASE_SECONDS=50, JOB_HANDLER_TIMEOUT_SECONDS=30)


def test_driver_desconocido_rechazado() -> None:
    # Un typo en el .env debe tumbar el arranque, no degradar al fake.
    with pytest.raises(ValidationError, match="EFFIS_DRIVER"):
        make(EFFIS_DRIVER="htpp")


def test_aemet_http_exige_api_key() -> None:
    with pytest.raises(ValidationError, match="AEMET_API_KEY"):
        make(AEMET_DRIVER="http", AEMET_API_KEY="")


def test_aemet_http_con_key_valida() -> None:
    s = make(AEMET_DRIVER="http", AEMET_API_KEY="k")
    assert s.AEMET_DRIVER == "http"
