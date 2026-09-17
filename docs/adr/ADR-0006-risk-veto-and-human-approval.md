# ADR-0006 — Risk Veto and human approval

- Status: Accepted
- Date: 2026-09-17
- Deciders: Human-approved Master Spec; implemented by Codex
- Supersedes: none
- Superseded by: none
- Related stage: PR-06 / PR-07

## Context

Optimistic research must not override hard risk constraints, and model recommendations must not become real orders without human authority. Approval and execution have different meanings and failure states.

## Decision

Risk Manager issues versioned hard Veto or soft flags with reason codes, Evidence, expiry, and release conditions. A hard Veto blocks BUY, ADD, and increased exposure; it cannot block risk-reducing REDUCE/EXIT. CIO cannot override a Veto.

All executable Decisions stop at `PENDING_APPROVAL`. A named human must approve within TTL. Rejection, revocation, expiry, material price/input drift, partial execution, and cancellation are distinct states. V1 binds live execution to `DisabledLiveExecutionAdapter`; paper and externally performed manual trades still preserve approval and execution records.

## Alternatives considered

### CIO override with explanation

Rejected because it makes a safety gate advisory.

### Approval implied by viewing or scheduling

Rejected because consent would be ambiguous and unauditable.

## Consequences

Some opportunities will be missed or require rerun after new Evidence. This is an accepted safety trade-off.

## Security and operational impact

Approval endpoints require strong authorization, audit, idempotency, CSRF protection where applicable, and immutable actor/time records. No secret or model output can simulate an approver.

## Migration and rollback

PR-06 implements Veto; PR-07 implements approval and disabled execution. Enabling broker execution requires a superseding/new ADR, threat model, recovery test, and explicit human authorization.

## References

- Master Spec sections 2.5, 8.3, 12, S3, S10
