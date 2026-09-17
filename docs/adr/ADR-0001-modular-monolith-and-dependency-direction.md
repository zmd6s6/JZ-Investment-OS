# ADR-0001 — Modular monolith and dependency direction

- Status: Accepted
- Date: 2026-09-17
- Deciders: Human-approved Master Spec; implemented by Codex
- Supersedes: none
- Superseded by: none
- Related stage: PR-00

## Context

The system has many domain concepts but is a single-user V1. Independent microservices would add deployment, consistency, tracing, and failure complexity before the domain is proven. The Master Spec requires inward dependencies and separate API/worker deployment units.

## Decision

Use one Python package as a modular monolith, deployed as `investment-api` and `investment-worker` processes from the same immutable image. Dependencies point `api/infrastructure/worker → application → domain`; domain code cannot import frameworks or adapters. PostgreSQL is the only required state service in V1.

Reserve the `web/` boundary, but defer React/Node metadata and lockfiles to PR-08. PR-00 has no stable UI contract beyond HTTP health, so an empty frontend would create maintenance without testing product behavior.

## Alternatives considered

### Microservices per engine

Rejected because distributed transactions and operations would dominate a personal-system V1.

### One undifferentiated application module

Rejected because it would make DSA, persistence, API, and LLM concerns leak into domain rules.

### Bootstrap React immediately

Rejected until PR-08 because there is no approved interaction contract to implement or test in PR-00.

## Consequences

Deployment stays simple and domain boundaries remain testable. API and worker can scale separately later. Developers must enforce boundaries with contract tests because Python packages do not provide hard module isolation.

## Security and operational impact

Fewer network surfaces reduce exposure. API and worker share dependencies, so a vulnerable dependency affects both and must be scanned centrally.

## Migration and rollback

Extract a module only through a superseding ADR after measuring a real scaling or isolation need. Reverting PR-00 removes only bootstrap code and containers; there is no domain migration.

## References

- Master Spec sections 3.2, 3.3, and PR-00
- `tests/contract/test_architecture_boundaries.py`
