"""Meta-test: cada endpoint invoca como maximo UN use case.

La orquestacion vive en los use cases, no en los routers: un endpoint que
compone dos use cases esta escondiendo un caso de uso compuesto que merece
nombre propio (o un evento). Analisis AST sobre los modulos api de cada
contexto.
"""

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[3] / "app"

# Excepciones justificadas: {"fichero.py::funcion": "motivo"}
ALLOWLIST: dict[str, str] = {}


def _route_functions(tree: ast.Module) -> list[ast.AsyncFunctionDef | ast.FunctionDef]:
    functions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and any(
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr in {"get", "post", "put", "patch", "delete"}
            for dec in node.decorator_list
        ):
            functions.append(node)
    return functions


def _use_case_instantiations(function: ast.AsyncFunctionDef | ast.FunctionDef) -> int:
    return sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id.endswith("UseCase")
        for node in ast.walk(function)
    )


def test_cada_endpoint_invoca_como_maximo_un_use_case() -> None:
    violations = []
    for api_file in APP_DIR.glob("*/api/**/*.py"):
        tree = ast.parse(api_file.read_text(encoding="utf-8"))
        for function in _route_functions(tree):
            key = f"{api_file.name}::{function.name}"
            if key in ALLOWLIST:
                continue
            count = _use_case_instantiations(function)
            if count > 1:
                violations.append(f"{key} instancia {count} use cases")

    assert not violations, (
        "endpoints con mas de un use case (mueve la orquestacion a un use case "
        f"compuesto o justifica en ALLOWLIST): {violations}"
    )
