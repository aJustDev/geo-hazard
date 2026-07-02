"""Job handlers registrados por efecto colateral.

Cada fuente anade aqui el import de su handler (effis_sync, ign_sync,
aemet_sync) cuando nace en su fase. Importar este paquete puebla el
job_registry; lo hace app.core.db_registry.
"""

import app.core.jobs.handlers.effis_sync  # noqa: F401
