"""Stable domain error codes and fail-closed exception type."""

from collections.abc import Mapping
from enum import StrEnum


class DomainErrorCode(StrEnum):
    INVALID_TRANSITION = "DOMAIN_INVALID_TRANSITION"
    TRANSITION_GUARD_FAILED = "DOMAIN_TRANSITION_GUARD_FAILED"
    INVALID_POLICY = "DOMAIN_INVALID_POLICY"
    INVARIANT_VIOLATION = "DOMAIN_INVARIANT_VIOLATION"
    FLOAT_NOT_ALLOWED = "DOMAIN_FLOAT_NOT_ALLOWED"
    NON_FINITE_DECIMAL = "DOMAIN_NON_FINITE_DECIMAL"
    OUT_OF_RANGE = "DOMAIN_OUT_OF_RANGE"
    TIMEZONE_REQUIRED = "DOMAIN_TIMEZONE_REQUIRED"
    REASON_REQUIRED = "DOMAIN_REASON_REQUIRED"
    RISK_ASSESSMENT_REQUIRED = "DOMAIN_RISK_ASSESSMENT_REQUIRED"
    RISK_VETO_BLOCKED = "DOMAIN_RISK_VETO_BLOCKED"
    HUMAN_APPROVAL_REQUIRED = "DOMAIN_HUMAN_APPROVAL_REQUIRED"
    APPROVAL_INVALID = "DOMAIN_APPROVAL_INVALID"
    LIVE_EXECUTION_DISABLED = "DOMAIN_LIVE_EXECUTION_DISABLED"
    LEARNING_AUTHORITY_EXCEEDED = "DOMAIN_LEARNING_AUTHORITY_EXCEEDED"


class DomainError(Exception):
    """Expected domain rejection with a machine-stable code."""

    def __init__(
        self,
        code: DomainErrorCode,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})
