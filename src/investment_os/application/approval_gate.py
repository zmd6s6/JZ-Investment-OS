"""Derive Decision state-machine approval facts from immutable human records."""

from investment_os.domain.approval import DecisionApprovalHistory
from investment_os.domain.enums import Action, ActorType, ApprovalAction
from investment_os.domain.state_machines import DecisionTransitionContext
from investment_os.domain.values import UtcTimestamp


def approval_transition_context(
    *,
    action: Action,
    history: DecisionApprovalHistory | None,
    as_of: UtcTimestamp,
    input_snapshot_matches: bool = False,
    price_within_tolerance: bool = False,
) -> DecisionTransitionContext:
    """Build only auditable approval facts; callers cannot invent approval booleans."""

    latest = history.latest_record_at(as_of) if history is not None else None
    active = history.active_approval_at(as_of) if history is not None else None
    return DecisionTransitionContext(
        action=action,
        approval_actor_type=ActorType.HUMAN if active is not None else None,
        approval_actor_id=active.actor_id if active is not None else None,
        approval_recorded=active is not None,
        approval_unexpired=active is not None,
        approval_revoked=latest is not None and latest.action is ApprovalAction.REVOKE,
        approval_rejected=latest is not None and latest.action is ApprovalAction.REJECT,
        approval_expired=(
            latest is not None
            and latest.action is ApprovalAction.APPROVE
            and not latest.is_valid_at(as_of)
        ),
        input_snapshot_matches=input_snapshot_matches,
        price_within_tolerance=price_within_tolerance,
    )
