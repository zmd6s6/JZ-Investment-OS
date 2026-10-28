"""Closed lifecycle for an owner-requested shadow analysis; never investment approval."""

from enum import StrEnum


class AnalysisStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_ANALYSIS = frozenset(
    {
        AnalysisStatus.SUCCEEDED,
        AnalysisStatus.DEGRADED,
        AnalysisStatus.FAILED,
        AnalysisStatus.CANCELLED,
    }
)


def require_analysis_transition(before: AnalysisStatus, after: AnalysisStatus) -> None:
    allowed = {
        AnalysisStatus.QUEUED: {AnalysisStatus.RUNNING, AnalysisStatus.CANCELLED},
        AnalysisStatus.RUNNING: set(TERMINAL_ANALYSIS),
    }
    if after not in allowed.get(before, set()):
        raise ValueError("ANALYSIS_TRANSITION_INVALID")
