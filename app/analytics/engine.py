"""Conexion DuckDB del plano analitico (ADR-0012).

In-memory y perezosa: los datos viven en los GeoParquet, que se releen en
cada consulta (siempre frescos, cero invalidacion de cache; a volumenes
ibericos releer cuesta milisegundos). No hay fichero .duckdb persistente.

Limites deliberadamente conservadores: este proceso convive con la API y
con Postgres en el mismo servidor; DuckDB por defecto se comeria todos los
cores y buena parte de la RAM.
"""

import threading

import duckdb

_THREADS = 2
_MEMORY_LIMIT = "512MB"

_lock = threading.Lock()
_connection: duckdb.DuckDBPyConnection | None = None


def cursor() -> duckdb.DuckDBPyConnection:
    """Cursor por peticion sobre la conexion compartida.

    La conexion (con spatial ya cargado) se comparte; el cursor no: cada
    peticion abre el suyo, que es barato y aisla su estado.
    """
    return _get_connection().cursor()


def _get_connection() -> duckdb.DuckDBPyConnection:
    global _connection
    with _lock:
        if _connection is None:
            con = duckdb.connect()
            con.execute("INSTALL spatial; LOAD spatial")
            con.execute(f"SET threads = {_THREADS}")
            con.execute(f"SET memory_limit = '{_MEMORY_LIMIT}'")
            _connection = con
        return _connection


def reset() -> None:
    """Cierra y descarta la conexion compartida (para tests)."""
    global _connection
    with _lock:
        if _connection is not None:
            _connection.close()
            _connection = None


__all__ = ["cursor", "reset"]
