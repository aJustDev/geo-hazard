import logging
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

JobFunc = Callable[[], Coroutine[Any, Any, None]]


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, JobFunc] = {}

    def register(self, job_name: str) -> Callable[[JobFunc], JobFunc]:
        """Decorador que registra un handler de job por nombre."""

        def decorator(func: JobFunc) -> JobFunc:
            self._jobs[job_name] = func
            logger.info("Registered job handler %s for %s", func.__name__, job_name)
            return func

        return decorator

    def get(self, job_name: str) -> JobFunc | None:
        return self._jobs.get(job_name)

    @property
    def registered_jobs(self) -> list[str]:
        return list(self._jobs.keys())


job_registry = JobRegistry()
