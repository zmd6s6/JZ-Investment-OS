"""Immutable, time-bounded human Decision approvals."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from investment_os.domain.enums import ApprovalAction
from investment_os.domain.errors import DomainError, DomainErrorCode
from investment_os.domain.values import UtcTimestamp


@dataclass(frozen=True, slots=True)
class DecisionApproval:
    """One append-only human action; only an unexpired APPROVE authorizes a Decision."""

    decision_id: UUID
    actor_id: str
    action: ApprovalAction
    occurred_at: UtcTimestamp
    expires_at: UtcTimestamp | None = None
    comment: str | None = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise DomainError(
                DomainErrorCode.APPROVAL_INVALID,
                "approval actor_id must not be blank",
            )
        if self.action is ApprovalAction.APPROVE:
            if self.expires_at is None:
                raise DomainError(
                    DomainErrorCode.APPROVAL_INVALID,
                    "an approval requires an expiry",
                )
            if self.expires_at.value <= self.occurred_at.value:
                raise DomainError(
                    DomainErrorCode.APPROVAL_INVALID,
                    "approval expiry must follow the approval time",
                )
        elif self.expires_at is not None:
            raise DomainError(
                DomainErrorCode.APPROVAL_INVALID,
                "only an approval may have an expiry",
            )
        if self.comment is not None and not self.comment.strip():
            raise DomainError(
                DomainErrorCode.APPROVAL_INVALID,
                "approval comment must not be blank when supplied",
            )

    def is_valid_at(self, as_of: UtcTimestamp) -> bool:
        """Return whether this record is currently a valid human approval.

        The TTL is half-open: approval is invalid at its exact expiry instant.
        """

        return (
            self.action is ApprovalAction.APPROVE
            and self.expires_at is not None
            and self.occurred_at.value <= as_of.value < self.expires_at.value
        )


@dataclass(frozen=True, slots=True)
class DecisionApprovalHistory:
    """Ordered append-only approval history for one Decision."""

    decision_id: UUID
    records: tuple[DecisionApproval, ...]

    def __post_init__(self) -> None:
        if not self.records:
            raise DomainError(
                DomainErrorCode.APPROVAL_INVALID,
                "approval history requires at least one record",
            )
        if any(record.decision_id != self.decision_id for record in self.records):
            raise DomainError(
                DomainErrorCode.APPROVAL_INVALID,
                "approval history records must belong to the same Decision",
            )
        timestamps = tuple(record.occurred_at.value for record in self.records)
        if timestamps != tuple(sorted(timestamps)):
            raise DomainError(
                DomainErrorCode.APPROVAL_INVALID,
                "approval history must be ordered by occurrence time",
            )

    def active_approval_at(self, as_of: UtcTimestamp) -> DecisionApproval | None:
        """Return the latest valid approval, unless a later human action superseded it."""

        latest = self.latest_record_at(as_of)
        return latest if latest is not None and latest.is_valid_at(as_of) else None

    def latest_record_at(self, as_of: UtcTimestamp) -> DecisionApproval | None:
        """Return the last immutable action visible at the requested business time."""

        prior_records = tuple(
            record for record in self.records if record.occurred_at.value <= as_of.value
        )
        if not prior_records:
            return None
        return prior_records[-1]
