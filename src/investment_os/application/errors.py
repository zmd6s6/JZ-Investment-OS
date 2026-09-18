"""Application-layer errors with stable, transport-independent codes."""

from collections.abc import Mapping
from enum import StrEnum


class ApplicationErrorCode(StrEnum):
    OPTIMISTIC_CONCURRENCY_CONFLICT = "PERSISTENCE_OPTIMISTIC_CONCURRENCY_CONFLICT"
    EVIDENCE_REFERENCE_UNAVAILABLE = "THESIS_EVIDENCE_REFERENCE_UNAVAILABLE"
    THESIS_CURRENT_VERSION_MISSING = "THESIS_CURRENT_VERSION_MISSING"
    JOB_ALREADY_RUNNING = "RELIABLE_JOB_ALREADY_RUNNING"
    IDEMPOTENCY_KEY_CONFLICT = "RELIABLE_JOB_IDEMPOTENCY_KEY_CONFLICT"


class ApplicationError(Exception):
    """Expected application rejection that is safe to map at outer boundaries."""

    def __init__(
        self,
        code: ApplicationErrorCode,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})
