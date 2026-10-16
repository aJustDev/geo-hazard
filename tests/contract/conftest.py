"""Contract tests contra los upstreams reales (job nocturno, nunca en PRs).

Validan el FORMATO de lo que sirve cada fuente, no los valores: que el driver
y el parser lo digieren sin ProtocolError y sin descartar registros, y que los
registros cumplen las invariantes de los tipos canonicos. Una fuente caida
(TransientError) salta el test: las caidas ya las vigilan /v1/sources/status
y la alerta de ADR-0019; aqui solo interesa un cambio de contrato.
"""

import logging
from collections.abc import Iterator

import pytest

pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def sin_registros_descartados(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    # Los parsers descartan registros malformados con un warning agregado en
    # vez de fallar: un cambio de formato que vacie el lote pasaria en verde
    # si no se mira el log.
    with caplog.at_level(logging.WARNING, logger="app.core"):
        yield
    descartes = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert descartes == []
