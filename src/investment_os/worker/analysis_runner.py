"""At-most-once automatic execution of a claimed run; external calls are never replayed."""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from investment_os.application.analysis_runs import (
    AnalysisCancelled,
    AnalysisLeaseLost,
    AnalysisStorePort,
)
from investment_os.application.investment_analysis import InvestmentAnalysisOrchestrator
from investment_os.domain.analysis_run import AnalysisStatus

SAFE_CODES = frozenset(
    {
        "ANALYSIS_NO_VALID_EVIDENCE",
        "ANALYSIS_MODEL_PROFILE_CHANGED",
        "ANALYSIS_DATA_PROFILE_CHANGED",
        "ANALYSIS_BUDGET_CHANGED",
        "ANALYSIS_EVIDENCE_NOT_FOUND",
        "ANALYSIS_EVIDENCE_TARGET_MISMATCH",
        "ANALYSIS_EVIDENCE_SNAPSHOT_TOO_LARGE",
        "ANALYSIS_RESEARCH_FAILED",
        "ANALYSIS_REQUIRED_ROLE_INVALID",
        "ANALYSIS_REQUIRED_ROLE_FAILED",
        "ANALYSIS_ROLE_EVIDENCE_UNAVAILABLE",
        "ANALYSIS_INPUT_HASH_MISMATCH",
    }
)


class AnalysisWorkerRunner:
    def __init__(
        self,
        store: AnalysisStorePort,
        orchestrator: InvestmentAnalysisOrchestrator,
        *,
        run_timeout_seconds: int = 600,
        recovery_seconds: int = 900,
    ):
        if run_timeout_seconds <= 0 or recovery_seconds <= run_timeout_seconds:
            raise ValueError("ANALYSIS_TIMEOUT_CONFIGURATION_INVALID")
        self._store = store
        self._orchestrator = orchestrator
        self._timeout = run_timeout_seconds
        self._recovery = recovery_seconds

    async def dispatch_due(self, *, now: datetime | None = None) -> dict[str, object]:
        current = now or datetime.now(UTC)
        interrupted = await self._store.expire_interrupted(
            older_than=current - timedelta(seconds=self._recovery)
        )
        claim = await self._store.claim_next()
        if claim is None:
            return {"claimed": 0, "interrupted": interrupted}
        run_id, lease, queued = claim
        try:
            async with asyncio.timeout(self._timeout):
                await self._orchestrator.run(run_id, lease, queued)
        except AnalysisLeaseLost:
            return {"claimed": 1, "lease_lost": True, "run_id": str(run_id)}
        except AnalysisCancelled:
            await self._store.finish(
                run_id,
                lease,
                status=AnalysisStatus.CANCELLED,
                error_code="ANALYSIS_CANCEL_REQUESTED",
            )
        except asyncio.CancelledError:
            with suppress(TimeoutError, AnalysisLeaseLost):
                await asyncio.wait_for(
                    asyncio.shield(
                        self._store.finish(
                            run_id,
                            lease,
                            status=AnalysisStatus.FAILED,
                            error_code="ANALYSIS_WORKER_STOPPED_RETRY_REQUIRED",
                        )
                    ),
                    timeout=5,
                )
            raise
        except Exception as exc:
            code = (
                "ANALYSIS_TIMEOUT"
                if isinstance(exc, TimeoutError)
                else str(exc)
                if isinstance(exc, ValueError) and str(exc) in SAFE_CODES
                else "ANALYSIS_EXECUTION_FAILED"
            )
            try:
                await self._store.step(
                    run_id, lease, stage="EXECUTION", status="FAILED", payload={}, reason_code=code
                )
                await self._store.finish(
                    run_id, lease, status=AnalysisStatus.FAILED, error_code=code
                )
            except AnalysisLeaseLost:
                pass
        result = await self._store.get(run_id)
        return {
            "claimed": 1,
            "run_id": str(run_id),
            "status": result.status.value,
            "interrupted": interrupted,
        }
