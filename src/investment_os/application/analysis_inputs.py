"""Typed persistence boundary for the input snapshot used by one analysis."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from investment_os.application.analysis_orchestrator import AnalysisEvidenceSource


@dataclass(frozen=True, slots=True)
class SelectedAnalysisEvidence:
    source: AnalysisEvidenceSource
    provenance: dict[str, Any]


class AnalysisInputsPort(Protocol):
    async def evidence(
        self,
        instrument_id: UUID,
        *,
        as_of: datetime,
        evidence_ids: tuple[UUID, ...] | None,
    ) -> tuple[SelectedAnalysisEvidence, ...]: ...

    async def policy_label(self, default: str) -> str: ...
