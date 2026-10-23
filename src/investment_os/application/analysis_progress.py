"""Versioned, truthful stage boundaries; no synthetic completion percentage."""

from typing import Literal, Protocol

AnalysisStage = Literal[
    "QUEUED",
    "PREPARING",
    "ROUND_ONE",
    "CONFLICTS",
    "ROUND_TWO",
    "PORTFOLIO",
    "RISK",
    "VALUATION_SIZING",
    "CIO",
    "CANCEL_REQUESTED",
    "FINISHED",
]
StageState = Literal["STARTED", "COMPLETED", "FAILED", "CANCELLED", "REQUESTED"]


class AnalysisCancelled(Exception):
    """Stop at a safe boundary, without attempting further paid work."""


class AnalysisProgress(Protocol):
    async def __call__(self, stage: AnalysisStage, state: StageState) -> None: ...
