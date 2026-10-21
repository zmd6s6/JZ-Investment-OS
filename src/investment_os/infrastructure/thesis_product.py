"""Atomic human Thesis editing: request idempotency, base-version CAS and immutable history."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from investment_os.application.errors import ApplicationError, ApplicationErrorCode
from investment_os.application.evidence import FreshnessStatus, derive_display_freshness
from investment_os.application.research_preview import content_hash
from investment_os.application.thesis import thesis_content_hash, thesis_content_payload
from investment_os.application.thesis_product import (
    SaveThesisCommand,
    ThesisContentInput,
    ThesisSaved,
    ThesisWorkspace,
    ThesisWorkspaceVersion,
)
from investment_os.domain.enums import ThesisState
from investment_os.domain.errors import DomainError
from investment_os.domain.state_machines import ThesisTransitionContext, transition_thesis
from investment_os.domain.values import UtcTimestamp
from investment_os.infrastructure.persistence.locks import advisory_lock_key
from investment_os.infrastructure.persistence.models import (
    EventLogRecord,
    EvidenceRecord,
    InstrumentRecord,
    InvestmentThesisRecord,
    ThesisVersionRecord,
)
from investment_os.infrastructure.persistence.uow import SqlAlchemyUnitOfWork
from investment_os.infrastructure.research_preview import append_event
from investment_os.infrastructure.thesis_engine import (
    SqlAlchemyThesisWriter,
    thesis_content_from_record,
)


def invalid(message: str) -> ApplicationError:
    return ApplicationError(ApplicationErrorCode.THESIS_WRITE_INVALID, message)


class SqlThesisProduct:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self._sessions = sessions

    async def workspace(self, instrument_id: UUID) -> ThesisWorkspace:
        async with self._sessions() as session:
            if await session.get(InstrumentRecord, instrument_id) is None:
                raise ApplicationError(
                    ApplicationErrorCode.INSTRUMENT_NOT_FOUND, "instrument not found"
                )
            thesis = await session.scalar(
                select(InvestmentThesisRecord).where(
                    InvestmentThesisRecord.instrument_id == instrument_id
                )
            )
            if thesis is None:
                return ThesisWorkspace(
                    instrument_id=instrument_id, current_version_id=None, versions=()
                )
            current = (
                await session.get(ThesisVersionRecord, thesis.current_version_id)
                if thesis.current_version_id
                else None
            )
            if current is None or current.thesis_id != thesis.id:
                raise invalid("Thesis current version is missing or belongs to another instrument")
            rows = list(
                await session.scalars(
                    select(ThesisVersionRecord)
                    .where(
                        ThesisVersionRecord.thesis_id == thesis.id,
                        ThesisVersionRecord.version <= current.version,
                    )
                    .order_by(ThesisVersionRecord.version.desc())
                )
            )
            versions = []
            for row in rows:
                try:
                    content = thesis_content_from_record(row)
                    if thesis_content_hash(content) != row.content_hash:
                        raise ValueError("hash mismatch")
                    versions.append(
                        ThesisWorkspaceVersion(
                            id=row.id,
                            version=row.version,
                            parent_version_id=row.parent_version_id,
                            content_hash=row.content_hash,
                            created_at=row.created_at.isoformat(),
                            content=ThesisContentInput.model_validate(
                                thesis_content_payload(content)
                            ),
                            semantic_diff=row.metadata_json.get("semantic_diff"),
                        )
                    )
                except (ValueError, TypeError, KeyError, DomainError):
                    raise invalid("Thesis version cannot be safely interpreted") from None
            return ThesisWorkspace(
                instrument_id=instrument_id, current_version_id=current.id, versions=tuple(versions)
            )

    async def save(self, instrument_id: UUID, command: SaveThesisCommand) -> ThesisSaved:
        content = command.content.to_domain()
        fingerprint = content_hash(
            {
                "instrument_id": str(instrument_id),
                "command": command.model_dump(mode="json", exclude={"request_id"}),
            }
        )
        try:
            async with SqlAlchemyUnitOfWork(self._sessions) as uow:
                await uow.session.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": advisory_lock_key("thesis-product-request", str(command.request_id))},
                )
                replay = await uow.session.scalar(
                    select(EventLogRecord).where(
                        EventLogRecord.aggregate_type == "thesis_product_write",
                        EventLogRecord.aggregate_id == command.request_id,
                        EventLogRecord.event_type == "THESIS_PRODUCT_SAVED",
                    )
                )
                if replay is not None:
                    if replay.payload_json["request_hash"] != fingerprint:
                        raise ApplicationError(
                            ApplicationErrorCode.THESIS_REQUEST_CONFLICT,
                            "request id already used with another content",
                        )
                    return ThesisSaved.model_validate(replay.payload_json["result"])
                instrument = await uow.session.scalar(
                    select(InstrumentRecord.id)
                    .where(InstrumentRecord.id == instrument_id)
                    .with_for_update()
                )
                if instrument is None:
                    raise ApplicationError(
                        ApplicationErrorCode.INSTRUMENT_NOT_FOUND, "instrument not found"
                    )
                thesis = await uow.theses.get_by_instrument(instrument_id)
                current_id = thesis.current_version_id if thesis else None
                if current_id != command.expected_version_id:
                    raise ApplicationError(
                        ApplicationErrorCode.THESIS_EDIT_CONFLICT,
                        "Thesis changed since the editor was loaded",
                    )
                now = datetime.now(UTC)
                evidence = list(
                    await uow.session.scalars(
                        select(EvidenceRecord).where(EvidenceRecord.id.in_(content.evidence_ids))
                    )
                )
                if (
                    len(content.evidence_ids) > 50
                    or len(evidence) != len(content.evidence_ids)
                    or any(
                        e.instrument_id not in (None, instrument_id)
                        or e.ingested_at > now
                        or derive_display_freshness(
                            as_of=now,
                            available_at=e.available_at,
                            expires_at=e.expires_at,
                            ingested_status=e.freshness_status,
                        )
                        != FreshnessStatus.FRESH
                        for e in evidence
                    )
                ):
                    raise ApplicationError(
                        ApplicationErrorCode.THESIS_EVIDENCE_INVALID,
                        "Thesis requires current, available evidence for the instrument",
                    )
                current = await uow.thesis_versions.get(current_id) if current_id else None
                if thesis is not None and (current is None or current.thesis_id != thesis.id):
                    raise invalid("published Thesis version is invalid")
                if current is None:
                    if content.state not in (ThesisState.UNKNOWN, ThesisState.VALID):
                        raise invalid("first Thesis must be UNKNOWN or VALID")
                else:
                    try:
                        previous = thesis_content_from_record(current)
                    except (ValueError, TypeError, KeyError, DomainError):
                        raise invalid("published Thesis cannot be safely interpreted") from None
                    if thesis_content_hash(previous) != current.content_hash:
                        raise invalid("published Thesis hash mismatch")
                    if previous.state != content.state:
                        transition_thesis(
                            previous.state,
                            content.state,
                            ThesisTransitionContext(
                                evidence_supports_change=True, creates_new_version=True
                            ),
                            reason_codes=(content.change_reason.value,),
                            occurred_at=UtcTimestamp(now),
                        )
                result = await SqlAlchemyThesisWriter(self._sessions, now=lambda: now).write(
                    instrument_id=instrument_id,
                    content=content,
                    as_of=now,
                    correlation_id=command.request_id,
                    expected_current_content_hash=current.content_hash if current else None,
                    unit_of_work=uow,
                )
                stored = await uow.thesis_versions.get(result.thesis_version_id)
                assert stored is not None
                saved = ThesisSaved(
                    thesis_id=result.thesis_id,
                    version_id=result.thesis_version_id,
                    version=result.version,
                    content_hash=stored.content_hash,
                    created=result.created,
                )
                append_event(
                    uow.session,
                    "THESIS_PRODUCT_SAVED",
                    command.request_id,
                    stored.content_hash,
                    {
                        "instrument_id": str(instrument_id),
                        "request_hash": fingerprint,
                        "base_version_id": str(command.expected_version_id)
                        if command.expected_version_id
                        else None,
                        "result": saved.model_dump(mode="json"),
                    },
                    now,
                    aggregate="thesis_product_write",
                    topic="thesis.saved",
                    before_hash=current.content_hash if current else None,
                )
                await uow.commit()
                return saved
        except IntegrityError:
            raise ApplicationError(
                ApplicationErrorCode.THESIS_EDIT_CONFLICT, "concurrent Thesis write was rolled back"
            ) from None
        except DomainError:
            raise invalid(
                "Thesis content or state transition is invalid; "
                "BROKEN recovery needs a separate full review"
            ) from None
