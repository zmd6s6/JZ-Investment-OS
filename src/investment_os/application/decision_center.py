"""Typed human-only Decision Center commands; no execution adapter is exposed."""

import hashlib
import json
import unicodedata
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


def clean_text(value: str) -> str:
    return " ".join(
        "".join(
            " " if c.isspace() else "" if unicodedata.category(c).startswith("C") else c
            for c in value
        ).split()
    )


class CenterModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HumanCommand(CenterModel):
    request_id: UUID
    expected_revision: int = Field(ge=1)
    actor_id: str = Field(min_length=1, max_length=255)
    comment: str = Field(min_length=1, max_length=1000)
    confirmed: Literal[True]

    @model_validator(mode="after")
    def human_text(self) -> Self:
        if not clean_text(self.actor_id) or not clean_text(self.comment):
            raise ValueError("explicit human attribution and reason required")
        return self


class ManualExecutionCommand(HumanCommand):
    approval_id: UUID
    quantity: Decimal = Field(gt=0, allow_inf_nan=False, max_digits=38, decimal_places=18)
    price: Decimal = Field(gt=0, allow_inf_nan=False, max_digits=38, decimal_places=18)
    fees: Decimal = Field(ge=0, allow_inf_nan=False, max_digits=38, decimal_places=18)
    executed_at: AwareDatetime
    external_reference: str = Field(min_length=1, max_length=255)
    note: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def manual_text(self) -> Self:
        if not clean_text(self.external_reference) or not clean_text(self.note):
            raise ValueError("manual facts need a reference and note")
        return self


class DecisionCard(CenterModel):
    decision_id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    symbol: str
    action: str
    state: str
    revision: int
    created_at: datetime
    blockers: tuple[str, ...]


class CenterDetail(CenterModel):
    schema_version: Literal["1.0"] = "1.0"
    decision: DecisionCard
    as_of: datetime
    auto_trade: Literal[False] = False
    mode: Literal["RECORD_ONLY_NO_BROKER"] = "RECORD_ONLY_NO_BROKER"
    journal: dict[str, object]
    lineage: dict[str, object]
    history: tuple[dict[str, object], ...]
    approval_id: UUID | None
    approval_expires_at: datetime | None
    approved_quantity: Decimal | None
    filled_quantity: Decimal
    remaining_quantity: Decimal | None
    allowed_actions: tuple[str, ...]


def command_hash(action: str, command: HumanCommand) -> str:
    return hashlib.sha256(
        json.dumps(
            {"action": action, "command": command.model_dump(mode="json")},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class DecisionCenterPort(Protocol):
    async def list(self, *, portfolio_id: UUID | None = None) -> tuple[DecisionCard, ...]: ...

    async def get(self, decision_id: UUID) -> CenterDetail: ...

    async def act(
        self,
        decision_id: UUID,
        action: Literal["APPROVE", "REJECT", "REVOKE", "RECORD_EXECUTION"],
        command: HumanCommand,
    ) -> CenterDetail: ...
