"""Typed two-step research collection; candidate content never comes from the client."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, Protocol
from uuid import UUID, uuid4

from investment_os.application.evidence import normalize_artifact
from investment_os.application.research import ResearchArtifactDTO, ResearchRequest
from investment_os.application.research_runtime import ResearchProviderRuntime
from investment_os.domain.values import UtcTimestamp


def content_hash(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class ResearchPreviewError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ResearchCandidate:
    candidate_id: UUID
    artifact: ResearchArtifactDTO


@dataclass(frozen=True, slots=True)
class CandidateCommit:
    candidate_id: UUID
    evidence_id: UUID
    reused: bool


@dataclass(frozen=True, slots=True)
class ResearchPreview:
    preview_id: UUID
    request_hash: str
    profile_id: UUID
    instrument_id: UUID
    query: str
    created_at: datetime
    expires_at: datetime
    candidates: tuple[ResearchCandidate, ...]
    confirmation: tuple[CandidateCommit, ...] | None = None


class ResearchPreviewPort(Protocol):
    async def create_once(
        self,
        request_id: UUID,
        request_hash: str,
        fetch: Callable[[], Awaitable[ResearchPreview]],
    ) -> ResearchPreview: ...

    async def get(self, preview_id: UUID) -> ResearchPreview | None: ...

    async def confirm(
        self,
        preview_id: UUID,
        instrument_id: UUID,
        candidate_ids: tuple[UUID, ...],
        *,
        now: datetime,
    ) -> tuple[CandidateCommit, ...]: ...


class ResearchPreviewService:
    def __init__(
        self,
        port: ResearchPreviewPort,
        runtime: ResearchProviderRuntime,
        *,
        now: Callable[[], datetime],
    ) -> None:
        self._port, self._runtime, self._now = port, runtime, now

    async def preview(
        self,
        *,
        request_id: UUID,
        profile_id: UUID,
        instrument_id: UUID,
        query: str,
        max_results: int,
    ) -> ResearchPreview:
        cleaned = query.strip()
        if not cleaned or len(cleaned) > 1000 or not 1 <= max_results <= 20:
            raise ResearchPreviewError("research_preview_request_invalid")
        digest = content_hash([str(profile_id), str(instrument_id), cleaned, max_results])

        async def fetch() -> ResearchPreview:
            artifacts = await self._runtime.fetch(
                profile_id=profile_id,
                request=ResearchRequest(
                    (instrument_id,),
                    UtcTimestamp(self._now()),
                    query=cleaned,
                    max_results=max_results,
                ),
            )
            if len(artifacts) > max_results:
                raise ResearchPreviewError("research_preview_response_invalid")
            fetched_at = UtcTimestamp(self._now())
            candidates = []
            for artifact in artifacts:
                if artifact.instrument_id != instrument_id:
                    raise ResearchPreviewError("research_preview_instrument_mismatch")
                artifact = replace(
                    artifact,
                    available_at=UtcTimestamp(
                        max(
                            artifact.available_at.value,
                            fetched_at.value,
                        )
                    ),
                )
                normalize_artifact(artifact, ingested_at=fetched_at.value)
                candidates.append(ResearchCandidate(uuid4(), artifact))
            return ResearchPreview(
                request_id,
                digest,
                profile_id,
                instrument_id,
                cleaned,
                fetched_at.value,
                fetched_at.value + timedelta(minutes=10),
                tuple(candidates),
            )

        return await self._port.create_once(request_id, digest, fetch)

    async def get(self, preview_id: UUID) -> ResearchPreview:
        preview = await self._port.get(preview_id)
        if preview is None:
            raise ResearchPreviewError("research_preview_not_found")
        return preview

    async def confirm(
        self,
        preview_id: UUID,
        instrument_id: UUID,
        candidate_ids: tuple[UUID, ...],
    ) -> tuple[CandidateCommit, ...]:
        if not 1 <= len(candidate_ids) <= 20 or len(set(candidate_ids)) != len(candidate_ids):
            raise ResearchPreviewError("research_preview_selection_invalid")
        return await self._port.confirm(
            preview_id, instrument_id, tuple(sorted(candidate_ids)), now=self._now()
        )


def dump_artifact(artifact: ResearchArtifactDTO) -> dict[str, Any]:
    return {
        "provider": artifact.provider,
        "provider_ref": artifact.provider_ref,
        "artifact_type": artifact.artifact_type,
        "source_name": artifact.source_name,
        "source_locator": artifact.source_locator,
        "source_tier": artifact.source_tier,
        "observed_at": artifact.observed_at.value.isoformat(),
        "effective_at": artifact.effective_at.value.isoformat(),
        "available_at": artifact.available_at.value.isoformat(),
        "expires_at": artifact.expires_at.value.isoformat() if artifact.expires_at else None,
        "payload": dict(artifact.payload),
        "source_schema_version": artifact.source_schema_version,
        "instrument_id": str(artifact.instrument_id) if artifact.instrument_id else None,
        "supersedes_id": str(artifact.supersedes_id) if artifact.supersedes_id else None,
    }


def load_artifact(value: dict[str, Any]) -> ResearchArtifactDTO:
    return ResearchArtifactDTO(
        provider=value["provider"],
        provider_ref=value["provider_ref"],
        artifact_type=value["artifact_type"],
        source_name=value["source_name"],
        source_locator=value["source_locator"],
        source_tier=value["source_tier"],
        observed_at=UtcTimestamp(datetime.fromisoformat(value["observed_at"])),
        effective_at=UtcTimestamp(datetime.fromisoformat(value["effective_at"])),
        available_at=UtcTimestamp(datetime.fromisoformat(value["available_at"])),
        expires_at=UtcTimestamp(datetime.fromisoformat(value["expires_at"]))
        if value["expires_at"]
        else None,
        payload=value["payload"],
        source_schema_version=value["source_schema_version"],
        instrument_id=UUID(value["instrument_id"]) if value["instrument_id"] else None,
        supersedes_id=UUID(value["supersedes_id"]) if value["supersedes_id"] else None,
    )
