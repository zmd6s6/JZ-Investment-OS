# ADR-0003 — Evidence immutability and time semantics

- Status: Accepted
- Date: 2026-09-17
- Deciders: Human-approved Master Spec; implemented by Codex
- Supersedes: none
- Superseded by: none
- Related stage: PR-02 / PR-03

## Context

Investment decisions must be reconstructed from what was actually available at the time. Overwriting corrected data or conflating event time with ingestion time creates look-ahead bias and destroys auditability.

## Decision

Evidence is append-only and content-addressed. Corrections create a new record with `supersedes_id`; they never alter the historical payload. Persist UTC `observed_at`, `effective_at`, `available_at`, and `ingested_at`. Backtests and as-of reads may use a record only when `available_at <= simulation_time`.

Core immutable artifacts store `content_hash`, schema version, correlation/causation IDs, and provenance. Database values use `numeric`/`Decimal` and `timestamptz`.

## Alternatives considered

### Update the latest row in place

Rejected because past decisions would silently change meaning.

### Store only publication/effective date

Rejected because delayed availability and ingestion would permit future information in historical evaluation.

## Consequences

Storage grows and callers need as-of queries, but decisions, replays, and backtests remain reproducible.

## Security and operational impact

Immutable raw payloads may contain sensitive text. Retention, access, encryption, and redaction apply at ingestion; secrets must never be persisted as Evidence.

## Migration and rollback

PR-02 creates append-only tables and PR-03 populates them. Schema changes add versions and forward migration; do not rewrite old hashes.

## References

- Master Spec sections 2.2, 2.3, 5.1, 5.2, S13
