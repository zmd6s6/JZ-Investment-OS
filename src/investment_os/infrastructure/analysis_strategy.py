"""Register and verify actual test artifacts without approving or activating them."""

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_governance import (
    AnalysisGovernancePlan,
    FrozenAnalysisStrategy,
)
from investment_os.application.analysis_models import digest
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.infrastructure.persistence.locks import advisory_lock_key
from investment_os.infrastructure.persistence.models import StrategyVersionRecord
from investment_os.infrastructure.research_preview import append_event

OWNER = "p6_test_artifact_registry"
EVENT = "ANALYSIS_TEST_STRATEGY_REGISTERED"


def runtime_code_ref(root: Path | None = None) -> str:
    """Content identity, not a claim about a Git commit or an installed dependency."""
    root = root or Path(__file__).resolve().parents[1]
    files = sorted(root.rglob("*.py"), key=lambda p: p.relative_to(root).as_posix())
    if not files:
        raise ValueError("runtime source is unavailable")
    fingerprints = []
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("runtime source must stay within the package")
        content = path.read_bytes().replace(b"\r\n", b"\n")
        fingerprints.append([path.relative_to(root).as_posix(), sha256(content).hexdigest()])
    return "sha256:" + digest(fingerprints)


def invalid() -> ApplicationError:
    return ApplicationError(
        ApplicationErrorCode.ANALYSIS_STRATEGY_INVALID,
        "test strategy identity, immutable record or runtime source cannot be verified",
    )


def frozen_record(row: StrategyVersionRecord) -> FrozenAnalysisStrategy:
    frozen = FrozenAnalysisStrategy.model_validate(
        {
            **row.rules_json,
            "id": row.id,
            "version": row.version,
            "status": row.status,
            "content_hash": row.content_hash,
        }
    )
    if (
        row.created_by != OWNER
        or row.approved_by is not None
        or row.code_ref != frozen.code_ref
        or row.prompt_bundle_hash != digest(row.rules_json["prompts"])
        or row.rules_json != frozen.rules()
    ):
        raise ValueError("strategy row is not the unapproved test artifact")
    return frozen


class SqlAnalysisStrategies:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        self._code_ref = runtime_code_ref()

    async def _current_code_ref(self) -> str:
        current = await asyncio.to_thread(runtime_code_ref)
        if current != self._code_ref:
            # A running process may still hold previously imported modules. Never label
            # hot-edited source as the code actually loaded by that process.
            raise ValueError("source changed after runtime assembly; restart required")
        return current

    async def freeze(self, plan: AnalysisGovernancePlan) -> FrozenAnalysisStrategy:
        try:
            code_ref = await self._current_code_ref()
            rules = {
                "schema_version": "1.0",
                "mode": "TEST_DEFAULT",
                "code_ref": code_ref,
                "formula": plan.formula.model_dump(mode="json"),
                "prompts": [p.model_dump(mode="json") for p in plan.prompts],
            }
            fingerprint = digest(rules)
            async with self._sessions() as session, session.begin():
                # Existing schema has a global version sequence. Lock the whole registry,
                # not just this hash, to serialize version allocation across distinct artifacts.
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": advisory_lock_key("strategy_version", "test_registry")},
                )
                rows = list(
                    await session.scalars(
                        select(StrategyVersionRecord).where(
                            StrategyVersionRecord.created_by == OWNER,
                            StrategyVersionRecord.content_hash == fingerprint,
                        )
                    )
                )
                if len(rows) > 1:
                    raise ValueError("ambiguous test strategy identity")
                if rows:
                    frozen = frozen_record(rows[0])
                    if frozen.rules() != rules:
                        raise ValueError("test strategy content differs")
                    return frozen
                version = (
                    await session.scalar(select(func.max(StrategyVersionRecord.version))) or 0
                ) + 1
                row = StrategyVersionRecord(
                    id=uuid4(),
                    version=version,
                    status="DRAFT",
                    rules_json=rules,
                    prompt_bundle_hash=digest(rules["prompts"]),
                    code_ref=code_ref,
                    approved_by=None,
                    content_hash=fingerprint,
                    created_by=OWNER,
                    correlation_id=uuid4(),
                )
                session.add(row)
                await session.flush()
                frozen = frozen_record(row)
                append_event(
                    session,
                    EVENT,
                    row.id,
                    fingerprint,
                    {
                        "strategy_version_id": str(row.id),
                        "snapshot": frozen.model_dump(mode="json"),
                    },
                    datetime.now(UTC),
                    aggregate="strategy_version",
                    topic="analysis.test_strategy",
                    actor_type="SYSTEM",
                    actor_id=OWNER,
                )
                return frozen
        except (ValueError, OSError, TypeError, KeyError):
            raise invalid() from None

    async def validate(self, plan: AnalysisGovernancePlan) -> None:
        try:
            frozen = plan.strategy
            if frozen is None or frozen.code_ref != await self._current_code_ref():
                raise ValueError("frozen code is missing or changed")
            async with self._sessions() as session:
                row = await session.get(StrategyVersionRecord, frozen.id)
                if row is None or frozen_record(row) != frozen:
                    raise ValueError("frozen strategy does not match the immutable record")
        except (ValueError, OSError, TypeError, KeyError):
            raise invalid() from None
