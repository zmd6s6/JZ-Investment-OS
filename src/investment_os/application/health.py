"""Infrastructure health contracts used by API and worker bootstrap paths."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class HealthCheck:
    """A sanitized readiness result safe for health endpoints and logs."""

    ready: bool
    detail: str


class ReadinessProbe(Protocol):
    """Port for checking whether required infrastructure is reachable."""

    async def check(self) -> HealthCheck: ...


@runtime_checkable
class AsyncClosable(Protocol):
    """Optional lifecycle contract for probes that own resources."""

    async def close(self) -> None: ...
