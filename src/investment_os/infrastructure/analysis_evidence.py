"""只读取本次冻结引用的不可变Evidence; 不获取来源或改写历史。"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.analysis_evidence import (
    AnalysisEvidenceView,
    EvidenceCitation,
    SavedEvidenceText,
)
from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.evidence import derive_display_freshness, normalize_artifact
from investment_os.application.research import ResearchArtifactDTO
from investment_os.application.research_preview import content_hash
from investment_os.domain.errors import DomainError
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.persistence.models import AnalysisRunRecord, EvidenceRecord


def invalid() -> ApplicationError:
    return ApplicationError(
        ApplicationErrorCode.ANALYSIS_EVIDENCE_INVALID,
        "引用或资料内容与运行快照不一致, 未展示正文; 请核对记录, 不要重新发起付费分析。",
    )


def verified_texts(payload: dict[str, Any]) -> tuple[SavedEvidenceText, ...]:
    remaining = 64000
    result = []
    seen = set()
    for field in ("summary", "snippet", "text", "content", "description"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip() or value in seen:
            continue
        seen.add(value)
        length = min(20000, remaining)
        result.append(
            SavedEvidenceText(
                field=field,
                text=value[:length],
                original_length=len(value),
                truncated=len(value) > length,
            )
        )
        remaining -= min(len(value), length)
    return tuple(result)


class SqlAnalysisEvidenceReader:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._sessions, self._now = sessions, now

    async def read(self, run_id: UUID, evidence_id: UUID) -> AnalysisEvidenceView:
        try:
            return await self._read(run_id, evidence_id)
        except (ValueError, TypeError, KeyError, AttributeError, DomainError):
            raise invalid() from None

    async def _read(self, run_id: UUID, evidence_id: UUID) -> AnalysisEvidenceView:
        async with self._sessions() as session:
            run = await session.get(AnalysisRunRecord, run_id)
            if run is None:
                raise ApplicationError(
                    ApplicationErrorCode.ANALYSIS_RESEARCH_NOT_FOUND, "运行不存在。"
                )
            read_at = UtcTimestamp(self._now()).value
            base = dict(
                run_id=run.id,
                evidence_id=evidence_id,
                instrument_id=run.instrument_id,
                analysis_as_of=run.as_of,
                read_at=read_at,
            )
            snapshot = run.payload_json.get("input_snapshot")
            if snapshot is None:
                return AnalysisEvidenceView(**base, status="NOT_RECORDED")
            if (
                not isinstance(snapshot, dict)
                or snapshot.get("input_hash")
                != content_hash({k: v for k, v in snapshot.items() if k != "input_hash"})
                or UUID(snapshot["instrument_id"]) != run.instrument_id
                or UUID(snapshot["portfolio"]["portfolio_id"]) != run.portfolio_id
                or UtcTimestamp(datetime.fromisoformat(snapshot["as_of"])).value != run.as_of
            ):
                raise invalid()
            entries = snapshot["evidence"]
            if not isinstance(entries, list) or len(entries) > 50:
                raise invalid()
            identities = [UUID(entry["evidence_id"]) for entry in entries]
            if len(set(identities)) != len(identities):
                raise invalid()
            if evidence_id not in identities:
                raise ApplicationError(
                    ApplicationErrorCode.ANALYSIS_EVIDENCE_NOT_FOUND,
                    "该资料不属于本次冻结引用, 未读取其他资料。",
                )
            common = {**base, "input_hash": snapshot["input_hash"]}
            if snapshot.get("schema_version") != "1.0":
                return AnalysisEvidenceView(**common, status="SNAPSHOT_ONLY")
            try:
                citation = EvidenceCitation.model_validate(entries[identities.index(evidence_id)])
            except ValidationError:
                return AnalysisEvidenceView(**common, status="SNAPSHOT_ONLY")
            common["citation"] = citation
            record = await session.get(EvidenceRecord, evidence_id)
            if record is None:
                return AnalysisEvidenceView(**common, status="CONTENT_UNAVAILABLE")
            if record.instrument_id not in (None, run.instrument_id):
                raise invalid()
            for name in (
                "content_hash",
                "source_name",
                "source_locator",
                "source_tier",
                "observed_at",
                "effective_at",
                "available_at",
                "ingested_at",
                "expires_at",
            ):
                if getattr(record, name) != getattr(citation, name):
                    raise invalid()
            if citation.available_at > run.as_of or (
                citation.ingested_freshness_status is not None
                and citation.ingested_freshness_status != record.freshness_status
            ):
                raise invalid()
            metadata = record.metadata_json
            if not all(
                isinstance(metadata.get(key), str) and metadata[key]
                for key in ("provider", "provider_ref", "source_schema_version")
            ):
                return AnalysisEvidenceView(**common, status="SNAPSHOT_ONLY")
            if citation.provider is not None and citation.provider != metadata["provider"]:
                raise invalid()
            normalized = normalize_artifact(
                ResearchArtifactDTO(
                    provider=metadata["provider"],
                    provider_ref=metadata["provider_ref"],
                    source_schema_version=metadata["source_schema_version"],
                    artifact_type=record.evidence_type,
                    instrument_id=record.instrument_id,
                    source_name=record.source_name,
                    source_locator=record.source_locator,
                    source_tier=record.source_tier,
                    observed_at=UtcTimestamp(record.observed_at),
                    effective_at=UtcTimestamp(record.effective_at),
                    available_at=UtcTimestamp(record.available_at),
                    expires_at=UtcTimestamp(record.expires_at) if record.expires_at else None,
                    payload=record.payload_json,
                ),
                ingested_at=record.ingested_at,
            )
            if normalized.content_hash != citation.content_hash:
                raise invalid()
            title = next(
                (
                    record.payload_json[key]
                    for key in ("title", "headline")
                    if isinstance(record.payload_json.get(key), str)
                    and record.payload_json[key].strip()
                ),
                citation.summary,
            )

            def freshness(at: datetime) -> str:
                return derive_display_freshness(
                    as_of=at,
                    available_at=record.available_at,
                    expires_at=record.expires_at,
                    ingested_status=record.freshness_status,
                ).value

            return AnalysisEvidenceView(
                **common,
                status="VERIFIED",
                title=title[:1000],
                title_truncated=len(title) > 1000,
                texts=verified_texts(record.payload_json),
                freshness_at_run=freshness(run.as_of),
                freshness_now=freshness(read_at),
            )
