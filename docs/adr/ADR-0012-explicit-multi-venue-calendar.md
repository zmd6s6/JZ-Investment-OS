# ADR-0012 — Explicit multi-venue calendar semantics

- Status: Accepted
- Date: 2026-09-20
- Deciders: Human owner; implemented by Codex
- Supersedes: none
- Superseded by: none
- Related stage: PR-08

## Context

The owner has added A shares to the V1 research/simulation scope. Scheduler business time must not
silently use a U.S. timezone for Shanghai or Shenzhen sessions, and it must not infer exchange
holidays from weekdays. The Master Spec requires explicit business time, idempotent replay, and
synthetic or authorized data only.

## Decision

Support synthetic explicit calendars for `US_EQUITIES`, `SSE`, and `SZSE`. U.S. sessions use
`America/New_York`; SSE/SZSE sessions use `Asia/Shanghai`. Each session date and close time remains
caller-supplied; there is no implicit weekday, holiday, or external calendar provider. A Daily job
receives its calendar explicitly and validates that its `as_of` has the calendar's business date.

This ADR authorizes only calendar semantics for synthetic development. It does not authorize an A
share data provider, real portfolio import, A-share policy limits, brokerage connectivity, or live
trading.

## Alternatives considered

### Continue using a global New York timezone

Rejected because it produces incorrect A-share business dates and UTC close instants.

### Infer Chinese trading dates from weekdays

Rejected because mainland exchange holidays and exceptional closures must be explicit and auditable.

## Consequences

Calendar callers must select a venue and supply authoritative or synthetic session records. U.S.
callers retain the explicit `US_EQUITIES` default for compatibility. Future authorized calendar
providers can populate the same contract without changing job semantics.

## Security and operational impact

The venue enum rejects arbitrary timezone strings. External calendar inputs remain untrusted data
and must be validated before creating a session. No credential, order, or execution capability is
added.

## Migration and rollback

No database migration is required. Existing U.S. synthetic calendars retain their default venue.
Rollback is a code revert; any future provider integration requires a separate ADR and authorization.

## References

- Master Spec sections 1.2, 2.3, 14, 17.2, 18.2, and Appendix B
- ADR-0003 and ADR-0008
