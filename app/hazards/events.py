"""Tipos de evento del outbox que publica el contexto hazards.

Modulo neutro: lo comparten los use cases que publican y los handlers que
consumen, sin que unos importen a otros. El valor viaja persistido en
outbox_events.event_type: renombrarlo dejaria huerfanos los eventos pendientes.
"""

# Payload: source, inserted, updated, closed (AEMET y EFFIS) y batch_at, la
# marca de tiempo ISO 8601 de la transaccion del sync. Cada fila que el lote
# inserto lleva esa marca en created_at y cada fila que actualizo o cerro en
# updated_at: los avisos seleccionan el lote exacto con ella (ADR-0021).
BATCH_INGESTED = "hazards.batch_ingested"
