"""Importa por efecto colateral todos los modelos ORM y los event handlers.

Anadir un subsistema con tablas o handlers -> anadir un import aqui. Asi
`Base.metadata` queda completa para Alembic y el dispatcher queda poblado.
Lo importan `app.main` y `migrations/env.py`.
"""

import app.core.events.models  # noqa: F401
import app.core.jobs.handlers  # noqa: F401 - registra los job handlers
import app.core.jobs.models  # noqa: F401
import app.hazards.event_handlers.export_geoparquet  # noqa: F401 - registra el handler del outbox
import app.hazards.models  # noqa: F401
