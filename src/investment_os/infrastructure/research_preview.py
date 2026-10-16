"""Transactional preview cache and all-or-nothing evidence confirmation."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.evidence import (
    FreshnessStatus,
    derive_display_freshness,
    normalize_artifact,
)
from investment_os.application.research_preview import (
    CandidateCommit,
    ResearchCandidate,
    ResearchPreview,
    ResearchPreviewError,
    content_hash,
    dump_artifact,
    load_artifact,
)
from investment_os.infrastructure.evidence_ingestion import SqlAlchemyEvidenceIngestor
from investment_os.infrastructure.persistence.models import (
    AuditLogRecord,
    DataProviderProfileRecord,
    EventLogRecord,
    OutboxEventRecord,
    ResearchConfirmationRecord,
    ResearchPreviewRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork


def append_event(
    session: AsyncSession,
    operation: str,
    identity: UUID,
    digest: str,
    payload: dict[str, object],
    now: datetime,
    *,
    aggregate: str = "research_collection",
    topic: str = "research.collection",
    actor_type: str = "HUMAN",
    actor_id: str = "local_owner",
) -> None:
    session.add(
        AuditLogRecord(
            actor_type=actor_type,
            actor_id=actor_id,
            operation=operation,
            entity_type=aggregate,
            entity_id=identity,
            before_hash=None,
            after_hash=digest,
            ip_or_runtime_ref="product_ui",
            occurred_at=now,
            correlation_id=identity,
            created_by=aggregate,
            metadata_json={},
        )
    )
    event = EventLogRecord(
        event_type=operation,
        aggregate_type=aggregate,
        aggregate_id=identity,
        payload_json=payload,
        occurred_at=now,
        created_by=aggregate,
        correlation_id=identity,
        metadata_json={},
    )
    from uuid import uuid4

    event.id = uuid4()
    session.add(event)
    session.add(
        OutboxEventRecord(
            event_id=event.id,
            topic=topic,
            payload_json=payload,
            created_by=aggregate,
            correlation_id=identity,
            metadata_json={},
        )
    )


def _confirmation(record: ResearchConfirmationRecord) -> tuple[CandidateCommit, ...]:
    return tuple(
        CandidateCommit(UUID(item["candidate_id"]), UUID(item["evidence_id"]), item["reused"])
        for item in record.payload_json["results"]
    )


class SqlAlchemyResearchPreviews:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    async def _read(session: AsyncSession, record: ResearchPreviewRecord) -> ResearchPreview:
        confirmation = await session.get(ResearchConfirmationRecord, record.id)
        return ResearchPreview(
            record.id,
            record.request_hash,
            record.profile_id,
            record.instrument_id,
            record.query,
            record.created_at,
            record.expires_at,
            tuple(
                ResearchCandidate(UUID(item["candidate_id"]), load_artifact(item["artifact"]))
                for item in record.payload_json["candidates"]
            ),
            _confirmation(confirmation) if confirmation else None,
        )

    async def create_once(
        self, request_id: UUID, request_hash: str, fetch: Callable[[], Awaitable[ResearchPreview]]
    ) -> ResearchPreview:
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": request_id.int % (2**63)}
            )
            existing = await session.get(ResearchPreviewRecord, request_id)
            if existing:
                if existing.request_hash != request_hash:
                    raise ResearchPreviewError("research_preview_request_conflict")
                return await self._read(session, existing)
            preview = await fetch()
            payload = {
                "schema_version": "1.0",
                "candidates": [
                    {
                        "candidate_id": str(item.candidate_id),
                        "artifact": dump_artifact(item.artifact),
                    }
                    for item in preview.candidates
                ],
            }
            encoded = json.dumps(payload, default=str)
            if len(encoded.encode()) > 1_000_000:
                raise ResearchPreviewError("research_preview_response_invalid")
            payload = json.loads(encoded)
            digest = content_hash(payload)
            session.add(
                ResearchPreviewRecord(
                    id=request_id,
                    request_hash=request_hash,
                    content_hash=digest,
                    profile_id=preview.profile_id,
                    instrument_id=preview.instrument_id,
                    query=preview.query,
                    expires_at=preview.expires_at,
                    payload_json=payload,
                    created_at=preview.created_at,
                    created_by="research_preview",
                    correlation_id=request_id,
                )
            )
            append_event(
                session,
                "RESEARCH_PREVIEW_CREATED",
                request_id,
                digest,
                {
                    "preview_id": str(request_id),
                    "profile_id": str(preview.profile_id),
                    "instrument_id": str(preview.instrument_id),
                    "count": len(preview.candidates),
                    "request_hash": request_hash,
                },
                preview.created_at,
            )
            return preview

    async def get(self, preview_id: UUID) -> ResearchPreview | None:
        async with self._sessions() as session:
            record = await session.get(ResearchPreviewRecord, preview_id)
            return await self._read(session, record) if record else None

    async def confirm(
        self,
        preview_id: UUID,
        instrument_id: UUID,
        candidate_ids: tuple[UUID, ...],
        *,
        now: datetime,
    ) -> tuple[CandidateCommit, ...]:
        async with SqlAlchemyUnitOfWork(self._sessions) as uow:
            record = (
                await uow.session.scalars(
                    select(ResearchPreviewRecord)
                    .where(ResearchPreviewRecord.id == preview_id)
                    .with_for_update()
                )
            ).one_or_none()
            if record is None:
                raise ResearchPreviewError("research_preview_not_found")
            if record.instrument_id != instrument_id:
                raise ResearchPreviewError("research_preview_instrument_mismatch")
            existing = await uow.session.get(ResearchConfirmationRecord, preview_id)
            if existing:
                prior_results = _confirmation(existing)
                if {item.candidate_id for item in prior_results} != set(candidate_ids):
                    raise ResearchPreviewError("research_preview_selection_conflict")
                return prior_results
            if now >= record.expires_at:
                raise ResearchPreviewError("research_preview_expired")
            profile = (
                await uow.session.scalars(
                    select(DataProviderProfileRecord)
                    .where(DataProviderProfileRecord.id == record.profile_id)
                    .with_for_update()
                )
            ).one_or_none()
            if profile is None or not profile.enabled or profile.credential_ref is None:
                raise ResearchPreviewError("research_preview_source_disabled")
            preview = await self._read(uow.session, record)
            candidates = {item.candidate_id: item for item in preview.candidates}
            if not set(candidate_ids) <= candidates.keys():
                raise ResearchPreviewError("research_preview_selection_invalid")
            normalized = {
                identity: normalize_artifact(candidates[identity].artifact, ingested_at=now)
                for identity in candidate_ids
            }
            if any(
                derive_display_freshness(
                    as_of=now,
                    available_at=item.available_at.value,
                    expires_at=item.expires_at.value if item.expires_at else None,
                    ingested_status=item.freshness_status,
                )
                != FreshnessStatus.FRESH
                for item in normalized.values()
            ):
                raise ResearchPreviewError("research_preview_candidate_unavailable")
            results = []
            for identity in sorted(
                candidate_ids, key=lambda identity: normalized[identity].content_hash
            ):
                result = await SqlAlchemyEvidenceIngestor.persist_in_uow(
                    uow, normalized[identity], preview_id
                )
                results.append(CandidateCommit(identity, result.evidence_id, result.reused))
            result_tuple = tuple(sorted(results, key=lambda item: item.candidate_id))
            digest = content_hash([str(identity) for identity in candidate_ids])
            uow.session.add(
                ResearchConfirmationRecord(
                    id=preview_id,
                    content_hash=digest,
                    payload_json={
                        "schema_version": "1.0",
                        "results": json.loads(
                            json.dumps([asdict(item) for item in result_tuple], default=str)
                        ),
                    },
                    created_by="research_confirmation",
                    created_at=now,
                    correlation_id=preview_id,
                )
            )
            append_event(
                uow.session,
                "RESEARCH_PREVIEW_CONFIRMED",
                preview_id,
                digest,
                {
                    "preview_id": str(preview_id),
                    "evidence_ids": [str(item.evidence_id) for item in result_tuple],
                },
                now,
            )
            await uow.commit()
            return result_tuple
