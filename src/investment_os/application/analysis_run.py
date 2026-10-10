"""Application port and service for persisted AnalysisRun records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from investment_os.application.errors import ApplicationError, ApplicationErrorCode


@dataclass(frozen=True, slots=True)
class AnalysisRunRead:
    id: UUID
    instrument_id: UUID
    portfolio_id: UUID
    source: str
    status: str
    as_of: datetime
    policy_version_label: str
    failure_code: str | None
    failure_detail: str | None
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AnalysisRunPort(Protocol):
    async def create(
        self,
        *,
        instrument_id: UUID,
        portfolio_id: UUID,
        source: str,
        as_of: datetime,
        policy_version_label: str,
        status: str,
        payload: dict[str, Any],
        failure_code: str | None = None,
        failure_detail: str | None = None,
    ) -> UUID: ...

    async def get(self, run_id: UUID) -> AnalysisRunRead | None: ...

    async def list_for_portfolio(
        self, *, portfolio_id: UUID, limit: int = 20
    ) -> tuple[AnalysisRunRead, ...]: ...

    async def list_for_instrument(
        self, *, instrument_id: UUID, limit: int = 20
    ) -> tuple[AnalysisRunRead, ...]: ...


class AnalysisRunService:
    def __init__(self, port: AnalysisRunPort) -> None:
        self._port = port

    async def record_success(
        self,
        *,
        instrument_id: UUID,
        portfolio_id: UUID,
        source: str,
        as_of: datetime,
        policy_version_label: str,
        payload: dict[str, Any],
    ) -> AnalysisRunRead:
        run_id = await self._port.create(
            instrument_id=instrument_id,
            portfolio_id=portfolio_id,
            source=source,
            as_of=as_of,
            policy_version_label=policy_version_label,
            status="SUCCEEDED",
            payload=payload,
        )
        run = await self._port.get(run_id)
        if run is None:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_NOT_FOUND,
                "analysis run disappeared after create",
            )
        return run

    async def record_failure(
        self,
        *,
        instrument_id: UUID,
        portfolio_id: UUID,
        source: str,
        as_of: datetime,
        policy_version_label: str,
        failure_code: str,
        failure_detail: str,
    ) -> AnalysisRunRead:
        run_id = await self._port.create(
            instrument_id=instrument_id,
            portfolio_id=portfolio_id,
            source=source,
            as_of=as_of,
            policy_version_label=policy_version_label,
            status="FAILED",
            payload={},
            failure_code=failure_code,
            failure_detail=failure_detail,
        )
        run = await self._port.get(run_id)
        if run is None:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_NOT_FOUND,
                "analysis run disappeared after create",
            )
        return run

    async def get(self, run_id: UUID) -> AnalysisRunRead:
        run = await self._port.get(run_id)
        if run is None:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_NOT_FOUND,
                "analysis run was not found",
                details={"run_id": str(run_id)},
            )
        return run

    async def list_for_portfolio(
        self, *, portfolio_id: UUID, limit: int = 20
    ) -> tuple[AnalysisRunRead, ...]:
        return await self._port.list_for_portfolio(portfolio_id=portfolio_id, limit=limit)
