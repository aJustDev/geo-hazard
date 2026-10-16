"""Tipos de evento del outbox que publica el contexto hazards.

Modulo neutro: lo comparten los use cases que publican y los handlers que
consumen, sin que unos importen a otros. El valor viaja persistido en
outbox_events.event_type: renombrarlo dejaria huerfanos los eventos pendientes.
"""

BATCH_INGESTED = "hazards.batch_ingested"
