# ADR-0002 — DSA adapter boundary

- Status: Accepted
- Date: 2026-09-17
- Deciders: Human-approved Master Spec; implemented by Codex
- Supersedes: none
- Superseded by: none
- Related stage: PR-03

## Context

DSA is the research/data foundation, while Investment OS owns investment meaning and persistent decision state. Direct imports or database coupling would prevent independent evolution and make upstream data authoritative by accident.

## Decision

All DSA access must implement application ports behind `infrastructure/dsa`. Only versioned internal DTOs cross the boundary. The adapter records provider references, source schema, availability time, raw-content hash, and normalized output. DSA outages or schema drift fail closed and cannot create synthetic Evidence.

DSA must never own or mutate Portfolio, Thesis, Risk Veto, Decision, Approval, Execution, Outcome, or Review state.

## Alternatives considered

### Share the DSA database

Rejected because private schemas have no compatibility contract and would erase system ownership boundaries.

### Import DSA internal Python modules

Rejected because release changes would become unbounded source-level breaking changes.

## Consequences

The adapter requires mapping and contract fixtures, but DSA can be replaced and historical decisions remain auditable when it is unavailable.

## Security and operational impact

Treat all DSA content as untrusted. Apply timeout, bounded retry, rate limits, schema validation, provenance, and prompt-injection isolation.

## Migration and rollback

PR-03 introduces the port and adapter. A provider change adds a new adapter and mapping version; old normalized records remain readable.

## References

- Master Spec sections 2.1, 16.1, 16.2, S14
