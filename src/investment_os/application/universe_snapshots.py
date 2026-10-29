"""Source-declared immutable membership, never independently verified market coverage."""

import csv
import hashlib
import io
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, field_validator

from investment_os.application.calendar_product import Confirmed
from investment_os.application.market_data import MarketDto, Text
from investment_os.application.opportunities import (
    Exact,
    FunnelQuery,
    FunnelRun,
    OpportunityError,
    OpportunityService,
)

MAX_IMPORT_ROWS = 1000  # Upload resource guard, not an investment or universe-selection rule.
MAX_CSV_CHARACTERS = 100_000


class UniverseScopeNotYetAvailable(OpportunityError):
    """Membership was unavailable at a historical screening business time."""


Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Description = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


class UniverseError(ValueError):
    def __init__(self, code: str, *, row: int | None = None):
        self.code, self.row = code, row
        super().__init__(code)


class UniverseDto(MarketDto):
    schema_version: Literal["1.0"] = "1.0"


class UniverseSource(UniverseDto):
    source_name: Name
    source_version: Name
    source_locator: Description
    market: Literal["SSE", "SZSE"]
    coverage_definition: Description
    observed_at: AwareDatetime
    effective_at: AwareDatetime
    available_at: AwareDatetime
    declared_total: int = Field(strict=True, ge=1, le=MAX_IMPORT_ROWS)
    completeness: Literal["DECLARED_COMPLETE", "PARTIAL", "UNKNOWN"]

    @field_validator("observed_at", "effective_at", "available_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class UniverseImport(UniverseDto):
    source: UniverseSource
    csv_text: Annotated[str, StringConstraints(min_length=1, max_length=MAX_CSV_CHARACTERS)]

    @field_validator("csv_text")
    @classmethod
    def utf8(cls, value: str) -> str:
        value.encode("utf-8")
        return value


class UniverseConfirm(UniverseImport):
    request_id: UUID
    preview_hash: Hash
    legal_use_acknowledgement: Confirmed
    declaration_acknowledgement: Confirmed


class UniverseMember(UniverseDto):
    instrument_id: UUID
    market: str
    symbol: str
    name: str
    currency: Literal["CNY"]
    asset_type: str


class UniversePreview(UniverseDto):
    source: UniverseSource
    members: tuple[UniverseMember, ...]
    file_hash: Hash
    members_hash: Hash
    preview_hash: Hash
    origin: Literal["SOURCE_DECLARED"] = "SOURCE_DECLARED"
    verification: Literal["UNVERIFIED"] = "UNVERIFIED"
    full_scan_supported: bool
    market_universe: Literal["NOT_PROVIDED"] = "NOT_PROVIDED"
    external_calls: Literal[0] = 0
    model_calls: Literal[0] = 0
    paid_calls: Literal[0] = 0
    auto_trade: Literal[False] = False


class UniverseSummary(UniverseDto):
    snapshot_id: UUID
    source: UniverseSource
    ingested_at: AwareDatetime
    evidence_id: UUID
    file_hash: Hash
    members_hash: Hash
    content_hash: Hash
    member_count: int = Field(ge=1, le=MAX_IMPORT_ROWS)
    origin: Literal["SOURCE_DECLARED"] = "SOURCE_DECLARED"
    verification: Literal["UNVERIFIED"] = "UNVERIFIED"
    market_universe: Literal["NOT_PROVIDED"] = "NOT_PROVIDED"
    external_calls: Literal[0] = 0
    model_calls: Literal[0] = 0
    paid_calls: Literal[0] = 0
    auto_trade: Literal[False] = False


class UniverseSnapshot(UniverseSummary):
    members: tuple[UniverseMember, ...]


class UniverseRun(UniverseDto):
    request_id: UUID
    snapshot_hash: Hash
    quote_source_name: Text
    fact_source_name: Text
    as_of: AwareDatetime | None = None  # None explicitly means first successful server-time run.
    candidate_limit: int = Field(strict=True, ge=1, le=20)
    industry_filter: Text | None = None
    min_profit_margin: Exact
    min_revenue_growth: Exact
    max_pe: Exact
    min_price_change: Exact

    @field_validator("max_pe")
    @classmethod
    def positive_pe(cls, value: str) -> str:
        if Decimal(value) <= 0:
            raise ValueError("max PE must be positive")
        return value


class UniverseOrigin(UniverseDto):
    run_id: UUID
    source: UniverseSummary


class UniverseBoundRun(UniverseDto):
    origin: UniverseOrigin
    run: FunnelRun


def parse_members(command: UniverseImport) -> tuple[str, ...]:
    try:
        text = command.csv_text.removeprefix("\ufeff")
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        if next(rows, None) != ["market", "symbol"]:
            raise UniverseError("UNIVERSE_CSV_HEADER", row=1)
        symbols = []
        for line, row in enumerate(rows, 2):
            if (
                len(row) != 2
                or not row[1]
                or len(row[1]) > 64
                or row[1] != row[1].strip().upper()
                or "\x00" in row[1]
            ):
                raise UniverseError("UNIVERSE_CSV_ROW", row=line)
            if row[0] != command.source.market:
                raise UniverseError("UNIVERSE_MARKET_MISMATCH", row=line)
            if row[1] in symbols:
                raise UniverseError("UNIVERSE_DUPLICATE", row=line)
            symbols.append(row[1])
            if len(symbols) > MAX_IMPORT_ROWS:
                raise UniverseError("UNIVERSE_IMPORT_LIMIT", row=line)
        if len(symbols) != command.source.declared_total:
            raise UniverseError("UNIVERSE_COUNT_MISMATCH")
        return tuple(symbols)
    except csv.Error:
        raise UniverseError("UNIVERSE_CSV_ROW") from None


class UniverseStorePort(Protocol):
    async def resolve(
        self, market: str, symbols: tuple[str, ...]
    ) -> tuple[UniverseMember, ...]: ...
    async def replay_import(self, command: UniverseConfirm) -> UniverseSnapshot | None: ...
    async def save_import(
        self, command: UniverseConfirm, preview: UniversePreview, now: datetime
    ) -> UniverseSnapshot: ...
    async def get(self, snapshot_id: UUID) -> UniverseSnapshot: ...
    async def list(self) -> tuple[UniverseSummary, ...]: ...
    async def replay_run(
        self, snapshot_id: UUID, command: UniverseRun
    ) -> UniverseBoundRun | None: ...
    async def save_run(
        self, snapshot: UniverseSnapshot, command: UniverseRun, run: FunnelRun
    ) -> UniverseBoundRun: ...
    async def origin(self, run_id: UUID) -> UniverseOrigin | None: ...


class UniverseSnapshotService:
    def __init__(
        self,
        store: UniverseStorePort,
        funnel: OpportunityService,
        *,
        now: Callable[[], datetime] | None = None,
    ):
        self.store, self.funnel = store, funnel
        self.now = now or (lambda: datetime.now(UTC))

    async def list(self) -> tuple[UniverseSummary, ...]:
        return await self.store.list()

    async def get(self, snapshot_id: UUID) -> UniverseSnapshot:
        return await self.store.get(snapshot_id)

    async def origin(self, run_id: UUID) -> UniverseOrigin | None:
        return await self.store.origin(run_id)

    async def preview(self, command: UniverseImport) -> UniversePreview:
        source = command.source
        if max(source.observed_at, source.effective_at, source.available_at) > self.now():
            raise UniverseError("UNIVERSE_FUTURE_SOURCE")
        symbols = parse_members(command)
        members = await self.store.resolve(source.market, symbols)
        if len(members) != len(symbols) or {m.symbol for m in members} != set(symbols):
            missing = next((s for s in symbols if s not in {m.symbol for m in members}), None)
            raise UniverseError(
                "UNIVERSE_UNKNOWN_MEMBER", row=symbols.index(missing) + 2 if missing else None
            )
        if len({m.instrument_id for m in members}) != len(members):
            raise UniverseError("UNIVERSE_IDENTITY_MISMATCH")
        members = tuple(sorted(members, key=lambda m: (m.market, m.symbol, str(m.instrument_id))))
        if any(m.market != source.market for m in members):
            raise UniverseError("UNIVERSE_MARKET_MISMATCH")
        file_hash = hashlib.sha256(command.csv_text.encode("utf-8")).hexdigest()
        members_hash = fingerprint([m.model_dump(mode="json") for m in members])
        return UniversePreview(
            source=source,
            members=members,
            file_hash=file_hash,
            members_hash=members_hash,
            preview_hash=fingerprint(
                {
                    "source": source.model_dump(mode="json"),
                    "file_hash": file_hash,
                    "members_hash": members_hash,
                }
            ),
            full_scan_supported=len(members) <= 200,
        )

    async def confirm(self, command: UniverseConfirm) -> UniverseSnapshot:
        replay = await self.store.replay_import(command)
        if replay:
            return replay
        preview = await self.preview(command)
        if preview.preview_hash != command.preview_hash:
            raise UniverseError("UNIVERSE_PREVIEW_CONFLICT")
        return await self.store.save_import(command, preview, self.now())

    async def run(self, snapshot_id: UUID, command: UniverseRun) -> UniverseBoundRun:
        replay = await self.store.replay_run(snapshot_id, command)
        if replay:
            return replay
        snapshot = await self.store.get(snapshot_id)
        if snapshot.content_hash != command.snapshot_hash:
            raise UniverseError("UNIVERSE_SNAPSHOT_CONFLICT")
        if snapshot.member_count > 200:
            raise UniverseError("UNIVERSE_SCAN_BOUND_EXCEEDED")
        as_of = command.as_of or self.now()
        if as_of < max(
            snapshot.source.observed_at,
            snapshot.source.effective_at,
            snapshot.source.available_at,
            snapshot.ingested_at,
        ):
            raise UniverseError("UNIVERSE_NOT_YET_AVAILABLE")
        query = FunnelQuery(
            **command.model_dump(exclude={"snapshot_hash", "as_of"}),
            instrument_ids=tuple(m.instrument_id for m in snapshot.members),
            scope_name=snapshot.source.source_name,
            scope_locator=f"universe_snapshot:{snapshot.snapshot_id}:{snapshot.content_hash}",
            as_of=as_of,
        )
        run = await self.funnel.prepare_run(query)
        return await self.store.save_run(snapshot, command, run)
