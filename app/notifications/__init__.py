"""Avisos push por area vigilada (ADR-0021).

Lee hazard_events tras cada lote (outbox) y avisa por ntfy o webhook a las
suscripciones cuya area toca. Puede importar de hazards models, events,
services y schemas; nunca su api, use_cases, repos ni event_handlers.
"""
