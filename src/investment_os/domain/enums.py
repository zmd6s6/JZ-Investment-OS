"""Closed vocabularies shared by the domain rules."""

from enum import StrEnum


class Action(StrEnum):
    WATCH = "WATCH"
    BUY = "BUY"
    ADD = "ADD"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    AVOID = "AVOID"


class RiskIntent(StrEnum):
    NONE = "NONE"
    TINY = "TINY"
    SMALL = "SMALL"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXIT = "EXIT"


class RiskGateState(StrEnum):
    UNKNOWN = "UNKNOWN"
    PASS = "PASS"
    VETO = "VETO"


class PositionBucket(StrEnum):
    CORE = "CORE"
    TACTICAL = "TACTICAL"


class InstrumentLifecycleState(StrEnum):
    DISCOVER = "DISCOVER"
    WATCH = "WATCH"
    SETUP = "SETUP"
    BUYABLE = "BUYABLE"
    HOLD = "HOLD"
    ADD = "ADD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    COOLDOWN = "COOLDOWN"
    ARCHIVED = "ARCHIVED"


class ThesisState(StrEnum):
    UNKNOWN = "UNKNOWN"
    VALID = "VALID"
    STRENGTHENING = "STRENGTHENING"
    WEAKENING = "WEAKENING"
    BROKEN = "BROKEN"


class DecisionState(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    RISK_VETOED = "RISK_VETOED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    EXECUTION_PENDING = "EXECUTION_PENDING"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"
    REVIEW_DUE = "REVIEW_DUE"
    REVIEWED = "REVIEWED"


class ApprovalAction(StrEnum):
    """Immutable human actions recorded against a Decision approval gate."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REVOKE = "REVOKE"


class BucketAction(StrEnum):
    """Separate Core/Tactical action recorded by a Decision Journal entry."""

    NONE = "NONE"
    BUY = "BUY"
    ADD = "ADD"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"


class StrategyProposalState(StrEnum):
    DRAFT = "DRAFT"
    BACKTEST_PENDING = "BACKTEST_PENDING"
    BACKTESTED = "BACKTESTED"
    SHADOW_PENDING = "SHADOW_PENDING"
    SHADOW_VALIDATED = "SHADOW_VALIDATED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SCHEDULED_ACTIVATION = "SCHEDULED_ACTIVATION"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ActorType(StrEnum):
    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"
    LEARNING_ENGINE = "LEARNING_ENGINE"


class PolicyStatus(StrEnum):
    TEST_DEFAULT = "TEST_DEFAULT"
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ReviewCadence(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
