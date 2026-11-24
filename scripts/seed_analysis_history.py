"""Seed explicitly labelled old synthetic history after a real Analysis Worker run.

Never claims inserted audit rows as Worker-produced evidence. Only a dedicated
mvp411 loopback *_analysis_synthetic database from ignored runtime config is used.
"""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from investment_os.application.analysis_runs import AnalysisStart, analysis_command_payload
from investment_os.application.portfolio_valuation import fingerprint
from investment_os.infrastructure.analysis_runs import audit
from investment_os.infrastructure.persistence.analysis_models import AnalysisRunRecord


async def main(config: dict[str, str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=UUID)
    parser.add_argument("--count", type=int, default=105)
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args()
    url = make_url(config["browser_url"])
    if url.host not in {"127.0.0.1", "localhost"} or not (
        url.database
        and url.database.startswith("mvp411_")
        and url.database.endswith("_analysis_synthetic")
    ):
        raise SystemExit("Only dedicated mvp411 loopback analysis synthetic DB is allowed")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session, session.begin():
            if args.snapshot:
                names = (
                    await session.scalars(
                        text(
                            "SELECT tablename FROM pg_tables "
                            "WHERE schemaname='public' ORDER BY tablename"
                        )
                    )
                ).all()
                result = {}
                for name in names:
                    rows = (
                        await session.scalars(
                            text(
                                f'SELECT to_jsonb(t)::text FROM "{name}" t '
                                "ORDER BY to_jsonb(t)::text"
                            )
                        )
                    ).all()
                    result[name] = hashlib.sha256(json.dumps(rows).encode()).hexdigest()
                print(json.dumps(result))
                return
            if not args.source_run or not 1 <= args.count <= 200:
                raise SystemExit("Require actual source run and bounded 1..200 seed count")
            original = await session.scalar(
                select(AnalysisRunRecord).where(AnalysisRunRecord.id == args.source_run)
            )
            if original is None or original.status not in {"SUCCEEDED", "DEGRADED"}:
                raise SystemExit("Require a genuinely finished source run")
            now = datetime.now(UTC)
            identifiers = []
            for index in range(args.count):
                identifier, request_id = uuid4(), uuid4()
                queued = json.loads(json.dumps(original.queued_input_json))
                queued["command"]["request_id"] = str(request_id)
                queued["queued_at"] = now.isoformat()
                session.add(
                    AnalysisRunRecord(
                        id=identifier,
                        request_id=request_id,
                        portfolio_id=original.portfolio_id,
                        instrument_id=original.instrument_id,
                        status="FAILED" if index % 2 else "CANCELLED",
                        queued_at=now,
                        started_at=None,
                        finished_at=now,
                        cancel_requested=False,
                        error_code="SYNTHETIC_SEEDED_HISTORY_NOT_WORKER",
                        request_hash=fingerprint(
                            analysis_command_payload(
                                AnalysisStart.model_validate(queued["command"])
                            )
                        ),
                        queued_input_json=queued,
                        version=1,
                        **audit(identifier),
                    )
                )
                identifiers.append(str(identifier))
            print(
                json.dumps(
                    {
                        "seeded_ids": identifiers,
                        "queued_at": now.isoformat(),
                        "kind": "SEEDED_SYNTHETIC_NOT_WORKER",
                    }
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    config = json.loads(Path(".runtime/mvp411-databases.json").read_text(encoding="utf-8-sig"))
    asyncio.run(main(config))
