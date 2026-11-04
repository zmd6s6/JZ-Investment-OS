"""Explicit complete synthetic numeric source; no Owner data, credentials, or policy changes."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker

from investment_os.application.analysis_risk_sizing import (
    NumericFact,
    NumericSourceSnapshot,
    NumericTarget,
    portfolio_identity,
)
from investment_os.application.market_data import ManualQuoteInput
from investment_os.application.policy_schema import InvestmentPolicySchema
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.application.research import ResearchArtifactDTO
from investment_os.domain.enums import ThesisState
from investment_os.domain.thesis import (
    EvidenceBackedClaim,
    PillarStatus,
    ThesisChangeReason,
    ThesisContent,
    ThesisPillar,
)
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.analysis_risk_sizing_models import (
    AnalysisNumericEvidenceRecord,
    AnalysisNumericSourceRecord,
)
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.manual_market_data import SqlManualMarketData
from investment_os.infrastructure.persistence.models import (
    InstrumentRecord,
    InvestmentPolicyRecord,
    InvestmentPolicyVersionRecord,
    PortfolioRecord,
    PositionRecord,
)
from investment_os.infrastructure.portfolio_valuation import SqlValuationInputs
from investment_os.infrastructure.thesis_engine import SqlAlchemyThesisWriter


def synthetic_rules():
    return {
        "schema_version": "sizing-rules-1.0",
        "formula_version": "synthetic-205-v1",
        "intent_weights": {
            "NONE": "0",
            "TINY": "0.01",
            "SMALL": "0.03",
            "NORMAL": "0.05",
            "HIGH": "0.08",
            "EXIT": "0",
        },
        "target_volatility": "0.2",
        "volatility_floor": "0.1",
        "volatility_scale_min": "0.5",
        "volatility_scale_max": "1",
        "reduce_fraction": "0.5",
        "max_instrument_volatility": "0.4",
        "correlation_attention_threshold": "0.8",
    }


async def seed_numeric(
    engine,
    *,
    source_kind="SYNTHETIC_FIXTURE",
    policy_active=True,
    missing_metric=None,
    liquidity="0.1",
    currency="CNY",
    source_expired=False,
    approved=True,
    missing_rules=False,
    missing_relation=False,
    corrupt_source=False,
):
    now = datetime.now(UTC)
    ids = {
        key: uuid4() for key in ("instrument", "portfolio", "policy", "policy_version", "snapshot")
    }
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    config = json.loads(
        await asyncio.to_thread(
            Path("config/investment-policy.test-default.json").read_text, encoding="utf-8"
        )
    )
    config["schema_version"] = "1.1"
    config["metadata"] = {
        "name": "synthetic-205-policy",
        "status": "ACTIVE" if policy_active else "TEST_DEFAULT",
    }
    config["sizing"] = None if missing_rules else synthetic_rules()
    InvestmentPolicySchema.model_validate_json(json.dumps(config))
    audit = {"created_by": "synthetic-205-fixture", "correlation_id": uuid4()}
    async with sessions() as session, session.begin():
        session.add(
            InstrumentRecord(
                id=ids["instrument"],
                symbol="629205",
                exchange="SSE",
                name="205合成测算标的",
                asset_type="EQUITY",
                currency=currency,
                sector="合成行业",
                lot_size=Decimal(100),
                **audit,
            )
        )
        session.add(
            InvestmentPolicyRecord(
                id=ids["policy"],
                name="synthetic-205-policy",
                status="ACTIVE",
                current_version_id=None,
                **audit,
            )
        )
        await session.flush()
        session.add(
            InvestmentPolicyVersionRecord(
                id=ids["policy_version"],
                policy_id=ids["policy"],
                version=1,
                config_json=config,
                content_hash=fingerprint(config),
                approved_by="synthetic-human" if approved else None,
                approved_at=now - timedelta(days=1) if approved else None,
                effective_from=now - timedelta(days=1),
                metadata_json={"approved_by_actor": "HUMAN"},
                **audit,
            )
        )
        session.add(
            PortfolioRecord(
                id=ids["portfolio"],
                name="205合成数值组合",
                base_currency="CNY",
                cash_balance=Decimal(97000),
                policy_id=ids["policy"],
                **audit,
            )
        )
        await session.flush()
        policy_record = await session.get(InvestmentPolicyRecord, ids["policy"])
        policy_record.current_version_id = ids["policy_version"]
        session.add(
            PositionRecord(
                portfolio_id=ids["portfolio"],
                instrument_id=ids["instrument"],
                core_quantity=Decimal(100),
                tactical_quantity=Decimal(200),
                core_average_cost=Decimal(8),
                tactical_average_cost=Decimal(9),
                avg_cost=Decimal("8.666666666666666667"),
                core_reason="合成Core",
                tactical_reason="合成Tactical",
                version=1,
                **audit,
            )
        )
    if currency == "CNY":
        await SqlManualMarketData(sessions).save_quote(
            ManualQuoteInput(
                request_id=uuid4(),
                instrument_id=ids["instrument"],
                source_name="synthetic-205-reference",
                source_locator="synthetic://205/manual-reference",
                currency="CNY",
                price="10",
                observed_at=now - timedelta(hours=1),
                effective_at=now - timedelta(hours=1),
                available_at=now - timedelta(hours=1),
                expires_at=now + timedelta(days=2),
            )
        )
    raw_facts = [
        {"metric": "REFERENCE_PRICE", "value": "10", "currency": currency},
        {"metric": "VOLATILITY", "value": "0.2", "currency": None},
        {"metric": "LIQUIDITY_CAPACITY", "value": liquidity, "currency": None},
        {"metric": "RISK_BUDGET_CAPACITY", "value": "0.1", "currency": None},
        {"metric": "CORRELATION", "value": "0.25", "currency": None},
    ]
    raw_facts = [
        {**row, "instrument_id": str(ids["instrument"])}
        for row in raw_facts
        if row["metric"] != missing_metric
    ]
    receipt = await SqlAlchemyEvidenceIngestor(sessions, now=lambda: now).ingest(
        ResearchArtifactDTO(
            provider="SYNTHETIC",
            provider_ref="205-numeric-" + str(ids["snapshot"]),
            artifact_type="MARKET",
            instrument_id=ids["instrument"],
            source_name="205明确合成数值来源",
            source_locator="synthetic://205/qualified-fixture",
            source_tier="PRIMARY",
            observed_at=UtcTimestamp(now - timedelta(hours=1)),
            effective_at=UtcTimestamp(now - timedelta(hours=1)),
            available_at=UtcTimestamp(now - timedelta(hours=1)),
            expires_at=UtcTimestamp(now + timedelta(days=1)),
            source_schema_version="numeric-facts-1.0",
            payload={"schema_version": "numeric-facts-1.0", "facts": raw_facts, "synthetic": True},
        )
    )
    ids["evidence"] = receipt.evidence_id
    written = await SqlAlchemyThesisWriter(sessions, now=lambda: now).write(
        instrument_id=ids["instrument"],
        as_of=now,
        content=ThesisContent(
            ThesisState.VALID,
            "205完整合成论点",
            (
                ThesisPillar(
                    "synthetic",
                    EvidenceBackedClaim("合成证据与数值", (receipt.evidence_id,)),
                    PillarStatus.VALID,
                ),
            ),
            (),
            (),
            (),
            (),
            ThesisChangeReason.NEW_EVIDENCE,
        ),
    )
    ids["thesis_version"] = written.thesis_version_id
    book = await SqlValuationInputs(sessions).capture(ids["portfolio"])
    source = NumericSourceSnapshot(
        snapshot_id=ids["snapshot"],
        portfolio_id=ids["portfolio"],
        instrument_id=ids["instrument"],
        policy_version_id=ids["policy_version"],
        portfolio_identity_hash=portfolio_identity(book),
        target=NumericTarget(
            instrument_id=ids["instrument"], currency=currency, sector="合成行业", lot_size="100"
        ),
        source_kind=source_kind,
        source_name="205明确合成数值来源",
        created_at=now,
        as_of=now,
        expires_at=now + timedelta(days=1)
        if not source_expired
        else now + timedelta(microseconds=1),
        facts=tuple(
            NumericFact.model_validate({**row, "evidence_id": receipt.evidence_id})
            for row in raw_facts
        ),
        content_hash="0" * 64,
    )
    source = source.model_copy(
        update={
            "content_hash": fingerprint(source.model_dump(mode="json", exclude={"content_hash"}))
        }
    )
    if corrupt_source:
        source = source.model_copy(update={"content_hash": "f" * 64})
    async with sessions() as session, session.begin():
        session.add(
            AnalysisNumericSourceRecord(
                id=source.snapshot_id,
                portfolio_id=source.portfolio_id,
                instrument_id=source.instrument_id,
                policy_version_id=source.policy_version_id,
                source_kind=source.source_kind,
                source_name=source.source_name,
                as_of=source.as_of,
                expires_at=source.expires_at,
                created_at=source.created_at,
                portfolio_identity_hash=source.portfolio_identity_hash,
                content_hash=source.content_hash,
                payload_json=source.model_dump(mode="json"),
                **audit,
            )
        )
        await session.flush()
        session.add_all(
            [
                AnalysisNumericEvidenceRecord(
                    snapshot_id=source.snapshot_id,
                    metric=fact.metric,
                    instrument_id=fact.instrument_id,
                    evidence_id=fact.evidence_id,
                )
                for fact in source.facts
                if not (missing_relation and fact.metric == "VOLATILITY")
            ]
        )
    return ids, source
