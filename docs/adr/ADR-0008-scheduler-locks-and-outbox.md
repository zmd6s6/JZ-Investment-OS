# ADR-0008 — Scheduler, advisory locks, and transactional outbox

- Status: Accepted
- Date: 2026-09-17
- Deciders: Human-approved Master Spec; implemented by Codex
- Supersedes: none
- Superseded by: none
- Related stage: PR-02 / PR-08

## Context

Daily through quarterly workflows must survive retries without duplicate Evidence or Decisions. V1 does not need Kafka or Redis, but database changes and emitted events must stay consistent.

## Decision

Use a persistent application scheduler with explicit market calendars and business `as_of`. PostgreSQL advisory locks prevent concurrent execution of the same logical job. `task_run.idempotency_key` provides business deduplication. Domain writes and `outbox_event` writes occur in one database transaction; a worker publishes outbox events with bounded retry and dead-letter visibility.

Jobs are at-least-once at the process boundary and exactly-once in business effect through idempotency. Every job supports dry-run and as-of replay.

## Alternatives considered

### In-memory cron only

Rejected because restarts lose state and concurrent workers duplicate work.

### Kafka/Redis queue in V1

Rejected because operations and failure modes exceed current scale.

## Consequences

PostgreSQL is a stronger operational dependency, but the topology remains small and observable.

## Security and operational impact

Administrative job triggers require authorization and audit. Locks have bounded leases/transactions; retries are capped and visible.

## Migration and rollback

PR-02 adds tables and primitives; PR-08 adds schedules. A future broker can replace outbox delivery without changing domain transactions.

## References

- Master Spec sections 3.2, 14, 17.2, S12
