# Project Status

> This is the single current-status record. Update it in the same change that advances a stage.

## Current snapshot

- Project: Personal AI Investment OS
- Current mode: `DEVELOPMENT`
- Active roadmap stage: `PR-02 — Persistence, Audit & Reliable Jobs`
- Stage state: `READY_FOR_REVIEW`
- Live trading: `FORBIDDEN`
- Canonical specification: `INVESTMENT_OS_MASTER_SPEC.md`
- Last status update: `2026-09-17`

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

## Not yet implemented or verified

- React/Node workspace, intentionally deferred to PR-08 by ADR-0001;
- DSA/Evidence ingestion, runtime Agent, scheduler cadence, UI, or Learning workflow functionality;
- business persistence workflows beyond the focused PR-02 repositories and reliability primitives;
- auditable Decision rejection actors and deterministic approval-expiry TTL guards, scheduled for PR-07;
- any complete end-to-end acceptance scenario S1–S15; PR-01 verifies only its domain-gate slices.

Nothing above may be inferred complete from the Master Spec alone.

## Next authorized work

Human-review PR-02 persistence, audit, transactional outbox, optimistic concurrency, migrations,
and reliable-job primitives. PR-01 and PR-02 remain available for human acceptance and are not
marked accepted by Codex. PR-03 is the next implementation stage after acceptance.

## Human decisions currently required

No investment-governance decision is required. The shipped Policy is `TEST_DEFAULT`; choosing real
limits remains a future human decision. Stage-branch commits and pushes are now authorized by the
owner; merging to `main` remains a separate human action.

## Roadmap

| Stage | State | Human acceptance | Notes |
|---|---|---|---|
| PR-00 | READY_FOR_REVIEW | Pending | Local/container and cumulative remote CI checks pass |
| PR-01 | READY_FOR_REVIEW | Pending | Reviewer blockers fixed; local and PR/push remote CI pass |
| PR-02 | READY_FOR_REVIEW | Pending | Local Definition of Done passes; remote CI pending push |
| PR-03 | PLANNED | Pending | DSA adapter, evidence, feature pipeline |
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
