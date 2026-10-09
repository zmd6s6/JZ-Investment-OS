"""CSV position import for PRODUCT-05: preview never writes; confirm is explicit.

Import never silently overwrites holdings. Conflicts with the current portfolio
must be resolved explicitly (skip / replace / update) and are audited.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.instrument_catalog import InstrumentCatalogPort
from investment_os.application.portfolio_book import (
    PortfolioBookService,
    PortfolioPositionInput,
    PortfolioView,
)
from investment_os.domain.instrument import InstrumentIdentity

RowStatus = Literal["VALID", "INVALID", "DUPLICATE", "CONFLICT"]
ConflictPolicy = Literal["SKIP", "REPLACE", "UPDATE"]

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

# Chinese reasons for product-facing validation messages.
_REASON_ZH = {
    "csv content must not be empty": "CSV 内容不能为空",
    "csv must include a header row": "CSV 必须包含表头行",
    "symbol must not be empty": "代码不能为空",
    "market must not be empty": "市场不能为空",
    "name must not be empty": "名称不能为空",
    "currency must be a 3-letter code": "币种必须是 3 位字母代码",
    "core_quantity is required": "缺少长期仓数量",
    "tactical_quantity is required": "缺少机动仓数量",
    "average_cost is required": "缺少买入均价",
    "core_quantity is not a valid decimal": "长期仓数量不是有效数字",
    "tactical_quantity is not a valid decimal": "机动仓数量不是有效数字",
    "average_cost is not a valid decimal": "买入均价不是有效数字",
    "core_quantity must be finite": "长期仓数量必须是有限数值",
    "tactical_quantity must be finite": "机动仓数量必须是有限数值",
    "average_cost must be finite": "买入均价必须是有限数值",
    "core_quantity must not contain separators": "长期仓数量不能包含逗号或空格",
    "tactical_quantity must not contain separators": "机动仓数量不能包含逗号或空格",
    "average_cost must not contain separators": "买入均价不能包含逗号或空格",
}


def _zh(reason: str) -> str:
    if reason in _REASON_ZH:
        return _REASON_ZH[reason]
    if reason.startswith("quantities and average_cost"):
        return "数量与均价不能为负数"
    if reason.startswith("zero quantity cannot"):
        return "数量为 0 时不能填写均价"
    if reason.startswith("duplicate of line"):
        return f"与第 {reason.rsplit(' ', 1)[-1]} 行重复"
    return reason


@dataclass(frozen=True, slots=True)
class CsvRowResult:
    line_number: int
    status: RowStatus
    reason: str | None
    normalized: PortfolioPositionInput | None
    existing_core_quantity: str | None = None
    existing_tactical_quantity: str | None = None
    existing_average_cost: str | None = None


@dataclass(frozen=True, slots=True)
class CsvImportPreview:
    total_rows: int
    valid: tuple[CsvRowResult, ...]
    invalid: tuple[CsvRowResult, ...]
    duplicates: tuple[CsvRowResult, ...]
    conflicts: tuple[CsvRowResult, ...]
    can_commit: bool
    requires_conflict_policy: bool
    content_hash: str = ""
    positions_hash: str = ""


@dataclass(frozen=True, slots=True)
class CsvImportAppliedRow:
    line_number: int
    market: str
    symbol: str
    action: Literal["CREATED", "REPLACED", "UPDATED", "SKIPPED"]
    before: dict[str, str] | None
    after: dict[str, str]
    proposed: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class ImportAuditRow:
    """Validated per-line audit payload persisted with import claims."""

    line_number: int
    market: str
    symbol: str
    action: str
    before: dict[str, str] | None
    after: dict[str, str] | None
    proposed: dict[str, str] | None = None

    @classmethod
    def from_source(cls, source: object) -> ImportAuditRow:
        if isinstance(source, ImportAuditRow):
            return source
        if isinstance(source, CsvImportAppliedRow):
            return cls(
                line_number=source.line_number,
                market=source.market,
                symbol=source.symbol,
                action=source.action,
                before=source.before,
                after=source.after,
                proposed=source.proposed,
            )
        if isinstance(source, dict):
            required = ("line_number", "market", "symbol", "action", "before", "after")
            missing = [key for key in required if key not in source]
            if missing:
                raise ApplicationError(
                    ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                    "import audit row is missing required fields",
                    details={"missing": missing},
                )
            line_number = source["line_number"]
            market = source["market"]
            symbol = source["symbol"]
            action = source["action"]
            if not isinstance(line_number, int) or not market or not symbol or not action:
                raise ApplicationError(
                    ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                    "import audit row has invalid field types or empty values",
                    details={"line_number": line_number, "market": market, "symbol": symbol},
                )
            return cls(
                line_number=line_number,
                market=str(market),
                symbol=str(symbol),
                action=str(action),
                before=source.get("before"),
                after=source.get("after"),
                proposed=source.get("proposed"),
            )
        # Attribute-bearing objects (dataclasses) only; never silent getattr defaults.
        try:
            line_number = int(source.line_number)  # type: ignore[attr-defined]
            market = str(source.market)  # type: ignore[attr-defined]
            symbol = str(source.symbol)  # type: ignore[attr-defined]
            action = str(source.action)  # type: ignore[attr-defined]
        except AttributeError as exc:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "import audit row is not a supported row payload",
            ) from exc
        return cls(
            line_number=line_number,
            market=market,
            symbol=symbol,
            action=action,
            before=getattr(source, "before", None),
            after=getattr(source, "after", None),
            proposed=getattr(source, "proposed", None),
        )


@dataclass(frozen=True, slots=True)
class CsvImportCommitResult:
    imported_count: int
    skipped_count: int
    conflict_policy: ConflictPolicy
    applied: tuple[CsvImportAppliedRow, ...]
    portfolio: PortfolioView
    audit_id: UUID


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


def parse_portfolio_csv(
    raw_text: str,
    *,
    existing: dict[tuple[str, str], dict[str, str]] | None = None,
) -> CsvImportPreview:
    if not raw_text.strip():
        raise ApplicationError(
            ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
            "CSV 内容不能为空",
        )
    sample = raw_text.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(sample))
    if reader.fieldnames is None:
        raise ApplicationError(
            ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
            "CSV 必须包含表头行",
        )
    headers = tuple((name or "").strip().lower() for name in reader.fieldnames)
    missing = [column for column in CSV_HEADER if column not in headers]
    if missing:
        raise ApplicationError(
            ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
            "CSV 表头缺少必需列",
            details={"missing": missing},
        )

    existing = existing or {}
    seen_keys: dict[tuple[str, str], int] = {}
    valid: list[CsvRowResult] = []
    invalid: list[CsvRowResult] = []
    duplicates: list[CsvRowResult] = []
    conflicts: list[CsvRowResult] = []
    total_rows = 0

    for offset, row in enumerate(reader, start=2):
        total_rows += 1
        try:
            identity = InstrumentIdentity(
                market=(row.get("market") or "").strip(),
                symbol=(row.get("symbol") or "").strip(),
                name=(row.get("name") or "").strip(),
                asset_type=(row.get("asset_type") or "").strip(),
                currency=(row.get("currency") or "").strip(),
                sector=(row.get("sector") or "").strip(),
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
                        reason=_zh(f"duplicate of line {seen_keys[key]}"),
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
            current = existing.get(key)
            if current is not None:
                conflicts.append(
                    CsvRowResult(
                        line_number=offset,
                        status="CONFLICT",
                        reason="组合中已有该代码; 请选择跳过、替换或累加",
                        normalized=normalized,
                        existing_core_quantity=current.get("core_quantity"),
                        existing_tactical_quantity=current.get("tactical_quantity"),
                        existing_average_cost=current.get("average_cost"),
                    )
                )
                continue
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
                    reason=_zh(str(exc)),
                    normalized=None,
                )
            )

    return CsvImportPreview(
        total_rows=total_rows,
        valid=tuple(valid),
        invalid=tuple(invalid),
        duplicates=tuple(duplicates),
        conflicts=tuple(conflicts),
        can_commit=bool(valid or conflicts) and not invalid,
        requires_conflict_policy=bool(conflicts),
        content_hash=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        positions_hash=_positions_hash(existing),
    )


def _positions_hash(existing: dict[tuple[str, str], dict[str, str]] | None) -> str:
    import json

    payload = {
        f"{market}|{symbol}": data for (market, symbol), data in sorted((existing or {}).items())
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class PortfolioCsvImportService:
    def __init__(
        self,
        portfolios: PortfolioBookService,
        catalog: InstrumentCatalogPort,
    ) -> None:
        self._portfolios = portfolios
        self._catalog = catalog

    async def _existing_map(self, portfolio_id: UUID) -> dict[tuple[str, str], dict[str, str]]:
        view = await self._portfolios.get_portfolio(portfolio_id)
        mapping: dict[tuple[str, str], dict[str, str]] = {}
        for position in view.positions:
            mapping[(position.market, position.symbol)] = {
                "core_quantity": str(position.core_quantity),
                "tactical_quantity": str(position.tactical_quantity),
                "average_cost": str(position.average_cost),
                "name": position.name,
                "core_average_cost": str(position.core_average_cost),
                "tactical_average_cost": str(position.tactical_average_cost),
                "core_reason": position.core_reason,
                "tactical_reason": position.tactical_reason,
                "operation": position.operation,
            }
        return mapping

    async def preview(self, portfolio_id: UUID, raw_text: str) -> CsvImportPreview:
        existing = await self._existing_map(portfolio_id)
        return parse_portfolio_csv(raw_text, existing=existing)

    async def confirm(
        self,
        *,
        portfolio_id: UUID,
        raw_text: str,
        conflict_policy: ConflictPolicy | None = None,
        expected_preview_hash: str | None = None,
        expected_positions_hash: str | None = None,
    ) -> CsvImportCommitResult:
        existing = await self._existing_map(portfolio_id)
        preview = parse_portfolio_csv(raw_text, existing=existing)

        if expected_preview_hash is not None and expected_preview_hash != preview.content_hash:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "CSV 内容已修改; 请重新预览后再确认",
            )
        if (
            expected_positions_hash is not None
            and expected_positions_hash != preview.positions_hash
        ):
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "持仓已在预览后发生变更; 请重新预览后再确认",
                details={"positions_hash": preview.positions_hash},
            )

        if preview.invalid:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "CSV 存在无效行; 禁止写入",
                details={
                    "invalid_count": len(preview.invalid),
                    "valid_count": len(preview.valid),
                    "conflict_count": len(preview.conflicts),
                },
            )
        if preview.requires_conflict_policy and conflict_policy is None:
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_CONFLICT_POLICY_REQUIRED,
                "CSV 与现有持仓冲突; 必须显式选择跳过、替换或累加",
                details={"conflict_count": len(preview.conflicts)},
            )
        if conflict_policy not in (None, "SKIP", "REPLACE", "UPDATE"):
            raise ApplicationError(
                ApplicationErrorCode.PORTFOLIO_WRITE_INVALID,
                "冲突处理方式无效",
            )

        import_hash = hashlib.sha256(
            (raw_text + "|" + (conflict_policy or "NONE")).encode("utf-8")
        ).hexdigest()
        existing_audit = await self._portfolios.find_import_audit(
            portfolio_id=portfolio_id, import_hash=import_hash
        )
        if existing_audit is not None:
            raise ApplicationError(
                ApplicationErrorCode.IDEMPOTENCY_KEY_CONFLICT,
                "相同 CSV 与冲突策略已导入过; 请勿重复确认",
                details={"audit_id": str(existing_audit), "import_hash": import_hash},
            )

        applied: list[CsvImportAppliedRow] = []
        imported = 0
        skipped = 0
        items: list[dict[str, object]] = []

        def _after(row: PortfolioPositionInput) -> dict[str, str]:
            core_avg = row.core_average_cost
            if core_avg is None:
                core_avg = row.average_cost if row.core_quantity != 0 else Decimal("0")
            tactical_avg = row.tactical_average_cost
            if tactical_avg is None:
                tactical_avg = row.average_cost if row.tactical_quantity != 0 else Decimal("0")
            return {
                "core_quantity": str(row.core_quantity),
                "tactical_quantity": str(row.tactical_quantity),
                "average_cost": str(row.average_cost),
                "core_average_cost": str(core_avg),
                "tactical_average_cost": str(tactical_avg),
                "core_reason": row.core_reason,
                "tactical_reason": row.tactical_reason,
            }

        def _queue(row: PortfolioPositionInput) -> None:
            core_avg = row.core_average_cost
            if core_avg is None:
                core_avg = row.average_cost if row.core_quantity != 0 else Decimal("0")
            tactical_avg = row.tactical_average_cost
            if tactical_avg is None:
                tactical_avg = row.average_cost if row.tactical_quantity != 0 else Decimal("0")
            items.append(
                {
                    "identity": InstrumentIdentity(
                        market=row.market,
                        symbol=row.symbol,
                        name=row.name,
                        asset_type=row.asset_type,
                        currency=row.currency,
                        sector=row.sector,
                    ),
                    "core_quantity": row.core_quantity,
                    "tactical_quantity": row.tactical_quantity,
                    "average_cost": row.average_cost,
                    "core_average_cost": core_avg,
                    "tactical_average_cost": tactical_avg,
                    "core_reason": row.core_reason,
                    "tactical_reason": row.tactical_reason,
                    "operation": row.operation,
                }
            )

        for row in preview.valid:
            assert row.normalized is not None
            key = (row.normalized.market, row.normalized.symbol)
            before = existing.get(key)
            _queue(row.normalized)
            imported += 1
            applied.append(
                CsvImportAppliedRow(
                    line_number=row.line_number,
                    market=row.normalized.market,
                    symbol=row.normalized.symbol,
                    action="REPLACED" if before else "CREATED",
                    before=before,
                    after=_after(row.normalized),
                    proposed=_after(row.normalized),
                )
            )

        for row in preview.conflicts:
            assert row.normalized is not None
            key = (row.normalized.market, row.normalized.symbol)
            before = existing.get(key)
            if conflict_policy == "SKIP" or conflict_policy is None:
                skipped += 1
                # After must reflect the actual landed state (unchanged), not the CSV proposal.
                applied.append(
                    CsvImportAppliedRow(
                        line_number=row.line_number,
                        market=row.normalized.market,
                        symbol=row.normalized.symbol,
                        action="SKIPPED",
                        before=before,
                        after=dict(before) if before else {},
                        proposed=_after(row.normalized),
                    )
                )
                continue

            if conflict_policy == "UPDATE" and before is not None:
                before_core = Decimal(before["core_quantity"])
                before_tactical = Decimal(before["tactical_quantity"])
                merged = PortfolioPositionInput(
                    market=row.normalized.market,
                    symbol=row.normalized.symbol,
                    name=row.normalized.name,
                    asset_type=row.normalized.asset_type,
                    currency=row.normalized.currency,
                    sector=row.normalized.sector,
                    core_quantity=before_core + row.normalized.core_quantity,
                    tactical_quantity=before_tactical + row.normalized.tactical_quantity,
                    average_cost=row.normalized.average_cost,
                    core_average_cost=(
                        Decimal(before["core_average_cost"])
                        if before.get("core_average_cost")
                        else row.normalized.core_average_cost
                    ),
                    tactical_average_cost=(
                        Decimal(before["tactical_average_cost"])
                        if before.get("tactical_average_cost")
                        else row.normalized.tactical_average_cost
                    ),
                    core_reason=before.get("core_reason") or row.normalized.core_reason,
                    tactical_reason=before.get("tactical_reason") or row.normalized.tactical_reason,
                    operation="UPDATE",
                )
            else:
                merged = row.normalized

            _queue(merged)
            imported += 1
            applied.append(
                CsvImportAppliedRow(
                    line_number=row.line_number,
                    market=merged.market,
                    symbol=merged.symbol,
                    action="UPDATED" if conflict_policy == "UPDATE" else "REPLACED",
                    before=before,
                    after=_after(merged),
                    proposed=_after(row.normalized),
                )
            )

        audit_id = await self._portfolios.apply_import_batch(
            portfolio_id=portfolio_id,
            import_hash=import_hash,
            conflict_policy=conflict_policy or "NONE",
            items=tuple(items),
            applied=tuple(applied),
            expected_positions_hash=expected_positions_hash,
        )
        portfolio = await self._portfolios.get_portfolio(portfolio_id)
        return CsvImportCommitResult(
            imported_count=imported,
            skipped_count=skipped + len(preview.duplicates),
            conflict_policy=conflict_policy or "NONE",  # type: ignore[arg-type]
            applied=tuple(applied),
            portfolio=portfolio,
            audit_id=audit_id,
        )


def new_audit_id() -> UUID:
    return uuid4()
