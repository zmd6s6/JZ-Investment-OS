# ADR-0010 — Security, prompt injection, and secret management

- Status: Accepted
- Date: 2026-09-17
- Deciders: Human-approved Master Spec; implemented by Codex
- Supersedes: none
- Superseded by: none
- Related stage: PR-00 and all stages

## Context

The system consumes adversarial external text and may later contain sensitive portfolio and execution data. External content must not change instructions, permissions, approvals, or tool access.

## Decision

Treat every external payload—including DSA, news, filings, web pages, and model output—as untrusted data. Separate system instructions from quoted content; use role-specific least-privilege tool allowlists; validate all structured output and all domain transitions. External text can create Evidence content only, never commands.

Secrets come from environment variables or a future secret manager, never source, fixtures, Prompt traces, logs, or Evidence. `.env` is ignored and `.env.example` contains placeholders. CI runs secret, dependency-vulnerability, and license checks. Local API binds only as configured; external exposure requires authentication, TLS, and a new threat review.

## Alternatives considered

### Rely on model refusal alone

Rejected because prompt injection is an authorization and data-flow problem, not only a model-behavior problem.

### Store credentials in local configuration committed to Git

Rejected because history is difficult to purge and CI/logs can expose it.

## Consequences

Tooling and schemas require more setup, and some content will fail closed. This is required for safe operation.

## Security and operational impact

Use sanitized structured logs, correlation IDs, dependency locks, bounded egress, minimal credentials, auditable approvals, and incident runbooks. A leaked secret must be rotated; deleting a file is insufficient.

## Migration and rollback

PR-00 establishes scanning and placeholders. Later stages add authentication and threat-specific tests. Security controls may only be superseded by equal or stronger controls.

## References

- Master Spec sections 16.4, 17.1, 18, S15
- `.github/workflows/ci.yml`
