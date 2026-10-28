"""Explicit synthetic Thesis seed for browser trace tests; never a product write API."""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from investment_os.domain.enums import ThesisState
from investment_os.domain.thesis import (
    EvidenceBackedClaim,
    InvalidationCondition,
    PillarStatus,
    ThesisChangeReason,
    ThesisContent,
    ThesisPillar,
)
from investment_os.infrastructure.thesis_engine import SqlAlchemyThesisWriter


async def seed(url: str, instrument: UUID, evidence: UUID, summary: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "postgresql+asyncpg"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or not parsed.path.endswith("_analysis_synthetic")
        or not summary.startswith("合成追溯论点")
    ):
        raise ValueError("Only explicitly named disposable loopback synthetic inputs are allowed")
    engine = create_async_engine(url)
    try:
        writer = SqlAlchemyThesisWriter(
            async_sessionmaker(engine, expire_on_commit=False), now=lambda: datetime.now(UTC)
        )
        result = await writer.write(
            instrument_id=instrument,
            as_of=datetime.now(UTC),
            content=ThesisContent(
                state=ThesisState.VALID,
                long_term_summary=summary,
                pillars=(
                    ThesisPillar(
                        key="synthetic-durability",
                        claim=EvidenceBackedClaim("合成追溯支柱", (evidence,)),
                        status=PillarStatus.VALID,
                    ),
                ),
                catalysts=(EvidenceBackedClaim("合成后续催化", (evidence,)),),
                risks=(EvidenceBackedClaim("合成论点风险", (evidence,)),),
                invalidation_conditions=(
                    InvalidationCondition(
                        condition="合成证伪条件",
                        measurement="synthetic-metric",
                        threshold="below 90%",
                        window="annual",
                    ),
                ),
                monitoring_conditions=("合成年度监控条件",),
                change_reason=ThesisChangeReason.NEW_EVIDENCE,
            ),
        )
        print(json.dumps({"version_id": str(result.thesis_version_id), "version": result.version}))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instrument", type=UUID, required=True)
    parser.add_argument("--evidence", type=UUID, required=True)
    parser.add_argument("--summary", required=True)
    args = parser.parse_args()
    asyncio.run(seed(os.environ["E2E_TRACE_DB_URL"], args.instrument, args.evidence, args.summary))
