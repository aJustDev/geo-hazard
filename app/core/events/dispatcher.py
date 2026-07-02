import asyncio
import logging
import traceback
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

HandlerFunc = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


@dataclass
class HandlerResult:
    handler_name: str
    success: bool
    error: str | None = None
    skipped: bool = False


@dataclass
class DispatchResult:
    results: list[HandlerResult] = field(default_factory=list)

    @property
    def all_succeeded(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def errors_summary(self) -> str:
        failed = [r for r in self.results if not r.success]
        return "\n---\n".join(f"[{r.handler_name}] {r.error}" for r in failed)


class EventDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, list[HandlerFunc]] = defaultdict(list)

    def register(self, event_type: str) -> Callable[[HandlerFunc], HandlerFunc]:
        """Decorador que registra un handler para un tipo de evento."""

        def decorator(func: HandlerFunc) -> HandlerFunc:
            self._handlers[event_type].append(func)
            logger.info("Registered handler %s for %s", func.__name__, event_type)
            return func

        return decorator

    async def dispatch(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        completed_handlers: set[str] | None = None,
    ) -> DispatchResult:
        """Ejecuta todos los handlers del evento con aislamiento y timeout.

        Cada handler corre en su propio try/except: un fallo no bloquea a los
        demas. Los handlers cuyo nombre este en `completed_handlers` se saltan
        (idempotencia por-handler entre reintentos).
        """
        handlers = self._handlers.get(event_type, [])
        if not handlers:
            logger.warning("No handlers registered for event_type=%s", event_type)
            return DispatchResult()

        completed = completed_handlers or set()
        result = DispatchResult()
        for handler in handlers:
            if handler.__name__ in completed:
                result.results.append(HandlerResult(handler.__name__, success=True, skipped=True))
                continue

            try:
                await asyncio.wait_for(
                    handler(payload),
                    timeout=settings.OUTBOX_HANDLER_TIMEOUT_SECONDS,
                )
                result.results.append(HandlerResult(handler.__name__, success=True))
            except Exception:
                tb = traceback.format_exc()
                logger.exception(
                    "Handler %s failed for event_type=%s", handler.__name__, event_type
                )
                result.results.append(HandlerResult(handler.__name__, success=False, error=tb))

        return result

    @property
    def registered_events(self) -> list[str]:
        return list(self._handlers.keys())


dispatcher = EventDispatcher()
