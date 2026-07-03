"""Job handlers registrados por efecto colateral.

Cada fuente anade aqui el import de su handler cuando nace en su fase.
Importar este paquete puebla el job_registry; lo hace app.core.db_registry.
"""

import app.core.jobs.handlers.aemet_sync  # noqa: F401
import app.core.jobs.handlers.effis_sync  # noqa: F401
import app.core.jobs.handlers.ign_sync  # noqa: F401
