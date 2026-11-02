from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class NtfyMessage:
    title: str
    body: str
    # Escala de ntfy: 1 (min) a 5 (urgente, salta el modo silencio).
    priority: int = 3
    tags: tuple[str, ...] = field(default_factory=tuple)
    click: str | None = None


class ChannelError(Exception):
    """Fallo de entrega. El mensaje nunca lleva la URL ni la credencial: solo
    la clase del fallo, el esquema y el host, porque acaba en logs y en la
    columna last_error de la suscripcion."""


__all__ = ["ChannelError", "NtfyMessage"]
