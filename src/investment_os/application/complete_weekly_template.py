"""Frozen predicate and exact full membership for version2 weekly replay."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from investment_os.application.market_data import MarketDto, Text
from investment_os.application.opportunities import Exact
from investment_os.application.universe_snapshots import Hash


class CompleteWeeklyTemplate(MarketDto):
    schema_version: Literal["2.0"] = "2.0"
    snapshot_id: UUID
    snapshot_hash: Hash
    request_id: UUID
    instrument_ids: Annotated[tuple[UUID, ...], Field(min_length=1, max_length=1000)]
    scope_name: Text
    scope_locator: Text
    scope_kind: Literal["LOCAL_EXPLICIT_LIST"] = "LOCAL_EXPLICIT_LIST"
    quote_source_name: Text
    fact_source_name: Text
    as_of: AwareDatetime
    candidate_limit: Annotated[int, Field(strict=True, ge=1, le=20)]
    rule_set_version: Literal["manual-screen-query-v1"] = "manual-screen-query-v1"
    industry_filter: Text | None = None
    min_profit_margin: Exact
    min_revenue_growth: Exact
    max_pe: Exact
    min_price_change: Exact

    @field_validator("as_of")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bounded_unique(self) -> Self:
        if len(self.instrument_ids) != len(set(self.instrument_ids)):
            raise ValueError("duplicate instruments are not allowed")
        if Decimal(self.max_pe) <= 0:
            raise ValueError("max PE must be positive")
        return self
