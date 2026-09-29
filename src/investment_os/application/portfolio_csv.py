"""CSV position import for PRODUCT-05: preview never writes; confirm is explicit."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.portfolio_book import (
    PortfolioBookService,
    PortfolioPositionInput,
    PortfolioView,
)
from investment_os.domain.instrument import InstrumentIdentity

RowStatus = Literal["VALID", "INVALID", "DUPLICATE"]

CSV_HEADER = (
    "market",
    "symbol",
    "name",
    "asset_type",
    "currency",
    "sector",
    "core_quantity",
    "tactical_quantity",
    "average_cost",
)


@dataclass(frozen=True, slots=True)
class CsvRowResult:
    line_number: int
    status: RowStatus
    reason: str | None
    normalized: PortfolioPositionInput | None


@dataclass(frozen=True, slots=True)
class CsvImportPreview:
    total_rows: int
    valid: tuple[CsvRowResult, ...]
    invalid: tuple[CsvRowResult, ...]
    duplicates: tuple[CsvRowResult, ...]
    can_commit: bool


@dataclass(frozen=True, slots=True)
class CsvImportCommitResult:
    imported_count: int
    skipped_count: int
    portfolio: PortfolioView


def _parse_decimal(raw: str, field: str) -> Decimal:
    text = raw.strip()
    if not text:
        raise ValueError(f"{field} is required")
    if any(ch in text for ch in (",", " ")):
        raise ValueError(f"{field} must not contain separators")
    try:
        value = Decimal(text)
    except Exception as exc:
        raise ValueError(f"{field} is not a valid decimal") from exc
    if not value.is_finite():
        raise ValueError(f"{field} must be finite")
    return value


def parse_portfolio_csv(raw_text: str) -> CsvImportPreview:
    if not raw_text.strip():
        raise ApplicationError(
            ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
            "csv content must not be empty",
        )
    sample = raw_text.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(sample))
    if reader.fieldnames is None:
        raise ApplicationError(
            ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
            "csv must include a header row",
        )
    headers = tuple((name or "").strip().lower() for name in reader.fieldnames)
    missing = [column for column in CSV_HEADER if column not in headers]
    if missing:
        raise ApplicationError(
            ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
            "csv header is missing required columns",
            details={"missing": missing},
        )

    seen_keys: dict[tuple[str, str], int] = {}
    valid: list[CsvRowResult] = []
    invalid: list[CsvRowResult] = []
    duplicates: list[CsvRowResult] = []
    total_rows = 0

    for offset, row in enumerate(reader, start=2):
        total_rows += 1
        try:
            market = (row.get("market") or "").strip()
            symbol = (row.get("symbol") or "").strip()
            name = (row.get("name") or "").strip()
            asset_type = (row.get("asset_type") or "").strip()
            currency = (row.get("currency") or "").strip()
            sector = (row.get("sector") or "").strip()
            identity = InstrumentIdentity(
                market=market,
                symbol=symbol,
                name=name,
                asset_type=asset_type,
                currency=currency,
                sector=sector,
            )
            core = _parse_decimal(row.get("core_quantity") or "", "core_quantity")
            tactical = _parse_decimal(row.get("tactical_quantity") or "", "tactical_quantity")
            average_cost = _parse_decimal(row.get("average_cost") or "", "average_cost")
            if core < 0 or tactical < 0 or average_cost < 0:
                raise ValueError("quantities and average_cost must not be negative")
            if core + tactical == 0 and average_cost != 0:
                raise ValueError("zero quantity cannot carry a non-zero average cost")
            key = identity.natural_key
            if key in seen_keys:
                duplicates.append(
                    CsvRowResult(
                        line_number=offset,
                        status="DUPLICATE",
                        reason=f"duplicate of line {seen_keys[key]}",
                        normalized=None,
                    )
                )
                continue
            seen_keys[key] = offset
            normalized = PortfolioPositionInput(
                market=identity.market,
                symbol=identity.symbol,
                name=identity.name,
                asset_type=identity.asset_type,
                currency=identity.currency,
                sector=identity.sector,
                core_quantity=core,
                tactical_quantity=tactical,
                average_cost=average_cost,
            )
            valid.append(
                CsvRowResult(
                    line_number=offset,
                    status="VALID",
                    reason=None,
                    normalized=normalized,
                )
            )
        except Exception as exc:  # validation is expected to reject malformed rows
            invalid.append(
                CsvRowResult(
                    line_number=offset,
                    status="INVALID",
                    reason=str(exc),
                    normalized=None,
                )
            )

    return CsvImportPreview(
        total_rows=total_rows,
        valid=tuple(valid),
        invalid=tuple(invalid),
        duplicates=tuple(duplicates),
        can_commit=bool(valid) and not invalid,
    )


class PortfolioCsvImportService:
    def __init__(self, portfolios: PortfolioBookService) -> None:
        self._portfolios = portfolios

    async def preview(self, raw_text: str) -> CsvImportPreview:
        return parse_portfolio_csv(raw_text)

    async def confirm(
        self,
        *,
        portfolio_id: UUID,
        raw_text: str,
    ) -> CsvImportCommitResult:
        preview = parse_portfolio_csv(raw_text)
        if not preview.can_commit:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "csv cannot be committed while invalid rows exist",
                details={
                    "invalid_count": len(preview.invalid),
                    "valid_count": len(preview.valid),
                },
            )
        imported = 0
        for row in preview.valid:
            if row.normalized is None:
                continue
            await self._portfolios.record_manual_position(
                portfolio_id=portfolio_id,
                position=row.normalized,
            )
            imported += 1
        portfolio = await self._portfolios.get_portfolio(portfolio_id)
        return CsvImportCommitResult(
            imported_count=imported,
            skipped_count=len(preview.duplicates),
            portfolio=portfolio,
        )
