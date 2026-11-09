"""Read-only lifecycle provenance; selection is never a lifecycle transition."""

import hashlib
import json
from datetime import datetime
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from investment_os.application.market_data import MarketDto
from investment_os.domain.enums import InstrumentLifecycleState


class LifecycleSnapshot(MarketDto):
    schema_version: Literal["1.0"] = "1.0"
    instrument_id: UUID
    as_of: AwareDatetime
    status: Literal["AVAILABLE", "UNKNOWN"]
    reason: Literal[
        "RECORDED_INITIAL_STATE",
        "STATE_NOT_PROVIDED",
        "STATE_NOT_YET_AVAILABLE",
        "STATE_HISTORY_UNAVAILABLE",
        "STATE_INVALID",
        "LIFECYCLE_PORT_NOT_PROVIDED",
    ]
    state: InstrumentLifecycleState | None = None
    source_record_id: UUID | None = None
    source_version: int | None = Field(default=None, ge=1)
    effective_at: AwareDatetime | None = None
    recorded_at: AwareDatetime | None = None
    thesis_version_id: UUID | None = None
    decision_id: UUID | None = None
    source_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.model_dump(mode="json", exclude={"source_hash"}),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    @model_validator(mode="after")
    def provenance(self) -> Self:
        if self.status == "AVAILABLE":
            if (
                self.reason != "RECORDED_INITIAL_STATE"
                or self.state is None
                or self.source_record_id is None
                or self.source_version != 1
                or self.effective_at is None
                or self.recorded_at is None
                or max(self.effective_at, self.recorded_at) > self.as_of
                or self.source_hash != self.fingerprint()
            ):
                raise ValueError("invalid lifecycle snapshot provenance")
        elif self.reason == "RECORDED_INITIAL_STATE" or any(
            value is not None
            for value in (
                self.state,
                self.source_record_id,
                self.source_version,
                self.effective_at,
                self.recorded_at,
                self.thesis_version_id,
                self.decision_id,
                self.source_hash,
            )
        ):
            raise ValueError("unknown lifecycle cannot claim a recorded state")
        return self


class OpportunityLifecyclePort(Protocol):
    async def read_lifecycle(self, instrument_id: UUID, as_of: datetime) -> LifecycleSnapshot: ...
