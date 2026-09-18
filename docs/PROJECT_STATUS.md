# Project Status

> This is the single current-status record. Update it in the same change that advances a stage.

## Current snapshot

- Project: Personal AI Investment OS
- Current mode: `DEVELOPMENT`
- Active roadmap stage: `PR-03 — DSA Adapter, Evidence & Feature Pipeline`
- Stage state: `IN_PROGRESS`
- Live trading: `FORBIDDEN`
- Canonical specification: `INVESTMENT_OS_MASTER_SPEC.md`
- Last status update: `2026-09-18`

## Established

- Master Engineering Specification exists and is the project SSOT.
- Root Codex working agreement exists in `AGENTS.md`.
- Persistent working mode exists in `docs/WORKING_MODE.md`.
- PR/ADR/stage documentation conventions exist.
- Python 3.12 project metadata and `uv.lock` exist.
- API and worker bootstrap health paths exist and have automated tests.
- PostgreSQL/API/worker Compose configuration parses successfully.
- PostgreSQL, API, and worker images build and reach healthy state; end-to-end smoke passes on host port 8100.
- CI, OpenAPI contract generation, dependency/license checks, and secret scanning are configured.
- Remote GitHub CI passes quality, Compose smoke, and independent Gitleaks jobs on the PR-01 branch.
- ADR-0001 through ADR-0010 are accepted as Master-Spec implementation decisions.
- Pure domain values, Investment Policy, and Instrument/Thesis/Decision/Strategy state machines exist.
- Core/Tactical, Risk Veto, human approval, and Learning authority invariants fail closed.
- Decision Risk Gate is explicit (`UNKNOWN|PASS|VETO`); missing assessment cannot be interpreted as PASS.
- ADR-0011 records the pure-domain and strict Policy-boundary implementation decision.
- Alembic revision `20260917_0001` creates all Master-Spec core tables plus normalized Evidence
  reference tables with UUID, numeric, timestamptz, constraint, and index contracts.
- Policy, Position, Thesis, and Decision persistence uses optimistic version checks.
- Audit/event history and immutable artifacts have database-enforced append-only guards.
- Unit of Work, transactional outbox, advisory locks, and idempotent TaskRun execution are verified
  against PostgreSQL 16.
- Compose applies migrations through a successful one-shot service before API/worker startup.
- Remote GitHub Actions run `35295158962` passes quality, Compose smoke, and independent Gitleaks
  jobs for the current PR-02 review head `cfb707d4f463a37605d6cae503f5a1f42aaceea9`.
- PR-02 is accepted and merged to `main` by PR #2 as `72a64ff797c25ec1c1e5e8d8196f9fe85ad44d5e`.

## Not yet implemented or verified

- React/Node workspace, intentionally deferred to PR-08 by ADR-0001;
- DSA/Evidence ingestion, runtime Agent, scheduler cadence, UI, or Learning workflow functionality;
- business persistence workflows beyond the focused PR-02 repositories and reliability primitives;
- auditable Decision rejection actors and deterministic approval-expiry TTL guards, scheduled for PR-07;
- any complete end-to-end acceptance scenario S1–S15; PR-01 verifies only its domain-gate slices.

Nothing above may be inferred complete from the Master Spec alone.

## Next authorized work

Implement PR-03: DSA adapter boundary, immutable Evidence ingestion, deterministic quality and
freshness handling, minimal Feature Pipeline, and data-lineage ingest API. PR-00 through PR-02 are
accepted and merged to `main`.

## Human decisions currently required

No investment-governance decision is required. The shipped Policy is `TEST_DEFAULT`; choosing real
limits remains a future human decision. Stage-branch commits and pushes are now authorized by the
owner; merging to `main` remains a separate human action.

## Roadmap

| Stage | State | Human acceptance | Notes |
|---|---|---|---|
| PR-00 | ACCEPTED | Merged to `main` | Delivered and accepted with the merged foundational work |
| PR-01 | ACCEPTED | Merged to `main` on 2026-09-17 | PR #1 merge commit `45b024109775e233049b8c7df1792b6190c67a58` |
| PR-02 | ACCEPTED | Merged to `main` on 2026-09-18 | PR #2 merge commit `72a64ff797c25ec1c1e5e8d8196f9fe85ad44d5e` |
| PR-03 | IN_PROGRESS | Pending | DSA adapter, evidence, feature pipeline |
| PR-04 | PLANNED | Pending | Thesis and shared memory |
| PR-05 | PLANNED | Pending | Agent runtime and committee |
| PR-06 | PLANNED | Pending | Portfolio, risk, sizing |
| PR-07 | PLANNED | Pending | Decision, approval, journal |
| PR-08 | PLANNED | Pending | Scheduler, reports, UI |
| PR-09 | PLANNED | Pending | Outcome, learning, hardening, release |

## Status update rules

- Do not mark a stage `READY_FOR_REVIEW` without recorded verification evidence.
- Do not mark a stage `ACCEPTED` on Codex's authority alone when human governance review is required.
- Add blockers with an owner, precise condition, attempted alternatives, and unblocking event.
- Keep detailed checklists and evidence in the corresponding `docs/stages/PR-XX.md`; keep this file concise.
