"""Canales de salida de los avisos (ADR-0021): ntfy y webhook firmado.

Infraestructura generica: no sabe que es un aviso, solo entrega un mensaje
ya construido. Drivers fake (dev/tests) y http, elegidos por
NOTIFICATIONS_DRIVER como los de las fuentes.
"""
